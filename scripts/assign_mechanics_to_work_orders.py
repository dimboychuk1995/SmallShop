from datetime import datetime, timezone
import random

from bson import ObjectId

from app import create_app
from app.extensions import get_master_db, get_mongo_client

SHOP_ID = ObjectId("69a8f9778dcda2c197ed9a34")
MECHANIC_EMAILS = ["sergey@ltsrepair.com", "ivan@ltsrepair.com"]


def main():
    app = create_app()
    with app.app_context():
        master = get_master_db()

        mechanics = list(master.users.find({"email": {"$in": MECHANIC_EMAILS}, "is_active": True}))
        mech_by_email = {str(m.get("email") or "").lower(): m for m in mechanics}
        missing = [e for e in MECHANIC_EMAILS if e.lower() not in mech_by_email]
        if missing:
            raise RuntimeError(f"Mechanics not found: {missing}")

        ordered_mechanics = [mech_by_email[e.lower()] for e in MECHANIC_EMAILS]

        shop = master.shops.find_one({"_id": SHOP_ID})
        if not shop:
            raise RuntimeError(f"Shop not found: {SHOP_ID}")

        db_name = shop.get("db_name")
        if not db_name:
            raise RuntimeError("Shop db_name is missing")

        shop_db = get_mongo_client()[str(db_name)]
        now = datetime.now(timezone.utc)

        def pick_assignment():
            # Around 35% split assignments and 65% single-mechanic assignments.
            if random.random() < 0.35:
                return [
                    {
                        "user_id": str(ordered_mechanics[0]["_id"]),
                        "name": ordered_mechanics[0].get("name") or "Sergey M",
                        "role": ordered_mechanics[0].get("role") or "mechanic",
                        "percent": 50.0,
                    },
                    {
                        "user_id": str(ordered_mechanics[1]["_id"]),
                        "name": ordered_mechanics[1].get("name") or "Ivan M",
                        "role": ordered_mechanics[1].get("role") or "mechanic",
                        "percent": 50.0,
                    },
                ]

            chosen = random.choice(ordered_mechanics)
            return [
                {
                    "user_id": str(chosen["_id"]),
                    "name": chosen.get("name") or "Mechanic",
                    "role": chosen.get("role") or "mechanic",
                    "percent": 100.0,
                }
            ]

        query = {"shop_id": SHOP_ID, "is_active": True}
        work_orders = list(shop_db.work_orders.find(query, {"_id": 1, "labors": 1, "blocks": 1}))

        updated = 0
        created_blocks = 0
        updated_blocks = 0

        for wo in work_orders:
            raw_labors = wo.get("labors") if isinstance(wo.get("labors"), list) else []
            if not raw_labors and isinstance(wo.get("blocks"), list):
                raw_labors = wo.get("blocks")

            assignment = pick_assignment()

            if not raw_labors:
                hours = f"{random.uniform(0.8, 4.5):.1f}"
                new_labors = [
                    {
                        "labor": {
                            "description": "General labor",
                            "hours": hours,
                            "rate_code": "standard",
                            "assigned_mechanics": assignment,
                        },
                        "parts": [],
                    }
                ]
                created_blocks += 1
            else:
                new_labors = []
                for block in raw_labors:
                    if not isinstance(block, dict):
                        continue
                    labor = block.get("labor") if isinstance(block.get("labor"), dict) else {}
                    hours_value = labor.get("hours")
                    if hours_value in (None, ""):
                        hours_value = f"{random.uniform(0.8, 4.5):.1f}"

                    labor["description"] = str(labor.get("description") or "General labor").strip() or "General labor"
                    labor["hours"] = str(hours_value)
                    labor["rate_code"] = str(labor.get("rate_code") or "standard").strip() or "standard"
                    labor["assigned_mechanics"] = assignment

                    block["labor"] = labor
                    if not isinstance(block.get("parts"), list):
                        block["parts"] = []

                    new_labors.append(block)
                    updated_blocks += 1

                if not new_labors:
                    hours = f"{random.uniform(0.8, 4.5):.1f}"
                    new_labors = [
                        {
                            "labor": {
                                "description": "General labor",
                                "hours": hours,
                                "rate_code": "standard",
                                "assigned_mechanics": assignment,
                            },
                            "parts": [],
                        }
                    ]
                    created_blocks += 1

            shop_db.work_orders.update_one(
                {"_id": wo["_id"]},
                {
                    "$set": {
                        "labors": new_labors,
                        "updated_at": now,
                    }
                },
            )
            updated += 1

        print(
            {
                "shop_db": db_name,
                "work_orders_found": len(work_orders),
                "work_orders_updated": updated,
                "created_labor_blocks": created_blocks,
                "updated_labor_blocks": updated_blocks,
                "mechanics_used": [str(m.get("email")) for m in ordered_mechanics],
            }
        )


if __name__ == "__main__":
    main()
