import re


BUSINESS_CATEGORIES = [
    {
        "key": "retail_trading",
        "label": "Retail / Trading",
        "businesses": [
            ("provision_store", "Provision Store"),
            ("mini_supermarket", "Mini Supermarket"),
            ("wholesale_shop", "Wholesale Shop"),
            ("building_materials", "Building Materials"),
            ("foodstuff_seller", "Foodstuff Seller"),
            ("boutique_clothing", "Boutique / Clothing"),
            ("phone_accessories", "Phone / Accessory Shop"),
            ("electronics_shop", "Electronics Shop"),
            ("cosmetics_shop", "Cosmetics Shop"),
            ("spare_parts", "Spare Parts Seller"),
            ("other_retail_trading", "Other Retail / Trading"),
        ],
    },
    {
        "key": "health",
        "label": "Health",
        "businesses": [
            ("pharmacy", "Pharmacy"),
            ("patent_medicine", "Patent Medicine Store"),
            ("clinic", "Clinic"),
            ("dental_clinic", "Dental Clinic"),
            ("eye_clinic", "Eye Clinic"),
            ("laboratory", "Laboratory / Test Center"),
            ("other_health", "Other Health Business"),
        ],
    },
    {
        "key": "education",
        "label": "Education",
        "businesses": [
            ("private_school", "Private School"),
            ("lesson_center", "Lesson Center"),
            ("creche_daycare", "Creche / Daycare"),
            ("skill_center", "Skill Acquisition Center"),
            ("tutorial_center", "Tutorial Center"),
            ("driving_school", "Driving School"),
            ("other_education", "Other Education Business"),
        ],
    },
    {
        "key": "beauty_personal_care",
        "label": "Beauty / Personal Care",
        "businesses": [
            ("hair_salon", "Hair Salon"),
            ("barbing_salon", "Barbing Salon"),
            ("nail_studio", "Nail Studio"),
            ("makeup_artist", "Makeup Artist"),
            ("spa_massage", "Spa / Massage"),
            ("beauty_products", "Beauty Product Seller"),
            ("other_beauty", "Other Beauty Business"),
        ],
    },
    {
        "key": "food_hospitality",
        "label": "Food / Hospitality",
        "businesses": [
            ("restaurant", "Restaurant"),
            ("food_vendor", "Food Vendor"),
            ("bakery", "Bakery"),
            ("catering", "Catering Business"),
            ("bar_lounge", "Bar / Lounge"),
            ("hotel_guest_house", "Hotel / Guest House"),
            ("frozen_food", "Frozen Food Seller"),
            ("other_food_hospitality", "Other Food / Hospitality"),
        ],
    },
    {
        "key": "services_artisans",
        "label": "Services / Artisans",
        "businesses": [
            ("tailor_fashion", "Tailor / Fashion Designer"),
            ("mechanic", "Mechanic"),
            ("electrician", "Electrician"),
            ("plumber", "Plumber"),
            ("car_wash", "Car Wash"),
            ("laundry_dry_cleaning", "Laundry / Dry Cleaning"),
            ("carpentry_furniture", "Carpentry / Furniture"),
            ("phone_repair", "Phone Repair"),
            ("other_services", "Other Service Business"),
        ],
    },
    {
        "key": "agriculture",
        "label": "Agriculture",
        "businesses": [
            ("feed_seller", "Feed Seller"),
            ("poultry_farm", "Poultry Farm"),
            ("fish_farm", "Fish Farm"),
            ("produce_trader", "Crop Produce Trader"),
            ("agrochemical_seller", "Agrochemical Seller"),
            ("livestock_seller", "Livestock Seller"),
            ("cooperative", "Farmers Cooperative"),
            ("other_agriculture", "Other Agriculture Business"),
        ],
    },
    {
        "key": "transport_logistics",
        "label": "Transport / Logistics",
        "businesses": [
            ("dispatch_delivery", "Dispatch / Delivery"),
            ("logistics_company", "Logistics Company"),
            ("car_hire", "Car / Bus Hire"),
            ("truck_supply", "Truck Supply"),
            ("fleet_owner", "Taxi / Keke Fleet"),
            ("other_transport", "Other Transport Business"),
        ],
    },
    {
        "key": "real_estate_rentals",
        "label": "Real Estate / Rentals",
        "businesses": [
            ("property_manager", "Property Manager"),
            ("estate_agent", "Estate Agent"),
            ("shortlet", "Short-let Apartment"),
            ("stall_rent", "Shop / Market Stall Rent"),
            ("equipment_rental", "Equipment Rental"),
            ("event_rental", "Event Chair / Canopy Rental"),
            ("other_real_estate", "Other Real Estate / Rental"),
        ],
    },
    {
        "key": "professional_office_services",
        "label": "Professional / Office Services",
        "businesses": [
            ("printing_photocopy", "Printing / Photocopy"),
            ("business_center", "Cyber Cafe / Business Center"),
            ("bookkeeping", "Bookkeeping / Accounting"),
            ("law_chamber", "Law Chamber"),
            ("consulting", "Consulting"),
            ("cleaning_service", "Cleaning Service"),
            ("other_professional", "Other Professional Service"),
        ],
    },
    {
        "key": "thrift_contribution",
        "label": "Thrift / Contributions",
        "businesses": [
            ("thrift_collector", "Thrift Collector"),
            ("ajo_esusu", "Ajo / Esusu"),
            ("savings_group", "Savings Group"),
            ("daily_contribution", "Daily Contribution"),
            ("cooperative_savings", "Cooperative Savings"),
            ("other_thrift", "Other Thrift / Contribution"),
        ],
    },
    {
        "key": "energy_fuel",
        "label": "Energy & Fuel",
        "businesses": [
            ("filling_station", "Filling Station / Fuel Station"),
            ("fuel_marketer", "Petroleum / Fuel Marketer"),
            ("kerosene_diesel", "Kerosene / Diesel Seller"),
            ("lpg_gas", "LPG / Cooking Gas Seller"),
            ("lubricants", "Lubricants / Engine Oil Seller"),
            ("other_energy", "Other Energy Business"),
        ],
    },
    {
        "key": "quarry_raw_materials",
        "label": "Quarry & Raw Materials",
        "businesses": [
            ("sand_seller", "Sand Seller"),
            ("granite_supplier", "Granite / Gravel Supplier"),
            ("quarry_owner", "Quarry Owner"),
            ("block_making", "Block Maker"),
            ("laterite_seller", "Laterite / Red Soil Seller"),
            ("other_raw_materials", "Other Raw Materials Business"),
        ],
    },
    {
        "key": "other",
        "label": "Other",
        "businesses": [
            ("other_business", "Other Business"),
        ],
    },
]

INDUSTRY_EXAMPLES = {
    "pharmacy": [
        "Mary bought paracetamol 1500",
        "I sold 2 packs amoxicillin at 2500",
        "stock",
    ],
    "patent_medicine": [
        "Mary bought malaria drug 2500",
        "I sold 3 bottles cough syrup at 1800",
        "stock",
    ],
    "private_school": [
        "Tunde paid school fees 50000",
        "Aisha balance 20000 due Friday",
        "customer summary Aisha",
    ],
    "lesson_center": [
        "Tunde paid lesson fee 15000",
        "Aisha balance 5000 due tomorrow",
        "dashboard",
    ],
    "hair_salon": [
        "Blessing did braids 15000 paid 10000",
        "I received 3000 for haircut",
        "today sales",
    ],
    "barbing_salon": [
        "I received 3000 for haircut",
        "John paid 2000",
        "today sales",
    ],
    "restaurant": [
        "I sold jollof rice 2500",
        "Ade bought food 4000 paid 2000",
        "today sales",
    ],
    "food_vendor": [
        "I sold 3 plates food at 2500",
        "Ade bought food 4000 paid 2000",
        "today sales",
    ],
    "tailor_fashion": [
        "Blessing paid 10000 for gown",
        "Aisha sewed dress 25000 paid 15000",
        "customer summary Aisha",
    ],
    "laundry_dry_cleaning": [
        "John washed clothes 5000 paid 3000",
        "I received 2500 for ironing",
        "today sales",
    ],
    "feed_seller": [
        "Ayo bought 5 bags feed at 18000",
        "I buy 20 bags feed from supplier at 15000 each",
        "stock",
    ],
    "dispatch_delivery": [
        "I received 2500 for delivery",
        "Bola delivery 6000 paid 4000",
        "today sales",
    ],
    "property_manager": [
        "Tenant A paid rent 200000",
        "Shop 4 balance 50000 due Friday",
        "unpaid debtors",
    ],
    "printing_photocopy": [
        "I received 3000 for printing",
        "Ayo printed flyers 15000 paid 10000",
        "today sales",
    ],
    "thrift_collector": [
        "Amina contributed 5000",
        "Tunde paid thrift 2000",
        "customer summary Amina",
    ],
    "filling_station": [
        "I sold 200 liters petrol at 750",
        "Tunde bought diesel 100 liters at 1200",
        "depot supplied 10000 liters PMS at 700 each",
    ],
    "fuel_marketer": [
        "Ade bought 5000 liters diesel at 1150 each",
        "I supply 10000 liters AGO to Bayo at 1100",
        "depot supplied 20000 liters at 1050 paid 15000000",
    ],
    "kerosene_diesel": [
        "I sold 50 liters kerosene at 800",
        "Ayo bought 30 liters diesel at 1200 paid 20000",
        "stock",
    ],
    "lpg_gas": [
        "Ade refilled 12.5kg cylinder at 15000",
        "I sold 3 cylinders gas at 12000 each",
        "today sales",
    ],
    "sand_seller": [
        "I sold 5 trips sand to Bayo at 35000",
        "Ade bought 3 trips sand at 30000 paid 50000",
        "stock",
    ],
    "granite_supplier": [
        "Ade bought 10 tonnes granite at 8000",
        "I supply 5 loads gravel to site A at 25000",
        "Bayo balance 50000 due Friday",
    ],
    "quarry_owner": [
        "I sold 3 trips granite to Emeka at 40000",
        "Bayo bought 5 tonnes stone at 7500 paid 25000",
        "dashboard",
    ],
    "block_making": [
        "Ade bought 500 blocks at 200 each",
        "I sold 1000 blocks to Bayo at 180 paid 150000",
        "stock",
    ],
}

HIGH_VALUE_TEMPLATE_KEYS = [
    "retail_trading",
    "pharmacy",
    "school",
    "salon_beauty",
    "artisan_services",
    "food_hospitality",
    "agriculture",
    "transport_logistics",
    "real_estate_rentals",
    "professional_services",
    "thrift_contribution",
]

BUSINESS_TEMPLATE_ALIASES = {
    "provision_store": "retail_trading",
    "mini_supermarket": "retail_trading",
    "wholesale_shop": "retail_trading",
    "building_materials": "retail_trading",
    "foodstuff_seller": "retail_trading",
    "boutique_clothing": "retail_trading",
    "phone_accessories": "retail_trading",
    "electronics_shop": "retail_trading",
    "cosmetics_shop": "retail_trading",
    "spare_parts": "retail_trading",
    "pharmacy": "pharmacy",
    "patent_medicine": "pharmacy",
    "private_school": "school",
    "lesson_center": "school",
    "creche_daycare": "school",
    "skill_center": "school",
    "tutorial_center": "school",
    "driving_school": "school",
    "hair_salon": "salon_beauty",
    "barbing_salon": "salon_beauty",
    "nail_studio": "salon_beauty",
    "makeup_artist": "salon_beauty",
    "spa_massage": "salon_beauty",
    "beauty_products": "salon_beauty",
    "tailor_fashion": "artisan_services",
    "mechanic": "artisan_services",
    "electrician": "artisan_services",
    "plumber": "artisan_services",
    "car_wash": "artisan_services",
    "laundry_dry_cleaning": "artisan_services",
    "carpentry_furniture": "artisan_services",
    "phone_repair": "artisan_services",
    "restaurant": "food_hospitality",
    "food_vendor": "food_hospitality",
    "bakery": "food_hospitality",
    "catering": "food_hospitality",
    "bar_lounge": "food_hospitality",
    "hotel_guest_house": "food_hospitality",
    "frozen_food": "food_hospitality",
    "feed_seller": "agriculture",
    "poultry_farm": "agriculture",
    "fish_farm": "agriculture",
    "produce_trader": "agriculture",
    "agrochemical_seller": "agriculture",
    "livestock_seller": "agriculture",
    "cooperative": "agriculture",
    "dispatch_delivery": "transport_logistics",
    "logistics_company": "transport_logistics",
    "car_hire": "transport_logistics",
    "truck_supply": "transport_logistics",
    "fleet_owner": "transport_logistics",
    "property_manager": "real_estate_rentals",
    "estate_agent": "real_estate_rentals",
    "shortlet": "real_estate_rentals",
    "stall_rent": "real_estate_rentals",
    "equipment_rental": "real_estate_rentals",
    "event_rental": "real_estate_rentals",
    "printing_photocopy": "professional_services",
    "business_center": "professional_services",
    "bookkeeping": "professional_services",
    "law_chamber": "professional_services",
    "consulting": "professional_services",
    "cleaning_service": "professional_services",
    "thrift_collector": "thrift_contribution",
    "ajo_esusu": "thrift_contribution",
    "savings_group": "thrift_contribution",
    "daily_contribution": "thrift_contribution",
    "cooperative_savings": "thrift_contribution",
    "filling_station": "energy_fuel",
    "fuel_marketer": "energy_fuel",
    "kerosene_diesel": "energy_fuel",
    "lpg_gas": "energy_fuel",
    "lubricants": "energy_fuel",
    "other_energy": "energy_fuel",
    "sand_seller": "quarry_raw_materials",
    "granite_supplier": "quarry_raw_materials",
    "quarry_owner": "quarry_raw_materials",
    "block_making": "quarry_raw_materials",
    "laterite_seller": "quarry_raw_materials",
    "other_raw_materials": "quarry_raw_materials",
}

INDUSTRY_TEMPLATES = {
    "retail_trading": {
        "label": "Retail / Trading",
        "fit": "shops that sell products, track stock, customers, suppliers, and daily sales",
        "basic_value": [
            "Record customer sales and payments",
            "Record direct counter sales",
            "See customer balances and basic dashboard",
        ],
        "go_value": [
            "Inventory and stock value",
            "Supplier purchases and supplier debt",
            "Product reports and debt reminders",
        ],
        "pro_value": [
            "Add staff to record sales",
            "Control what staff can view",
            "Owner sees staff performance and business-wide records",
        ],
        "examples": [
            "Ade bought rice 5000 paid 2000",
            "I sold 2 bags cement at 4500",
            "I buy 20 bags rice from Ayo at 15000 each",
        ],
        "quick_actions": [
            ("Record sale", "Send: Ade bought rice 5000 paid 2000"),
            ("Check stock", "Send: stock"),
            ("Supplier", "Send: suppliers"),
            ("Dashboard", "Send: dashboard"),
        ],
        "next_steps": [
            "After saving a sale, reply YES to save or EDIT to correct it.",
            "Send stock to see inventory.",
            "Send dashboard to review sales, debtors, and products.",
            "Send MENU to see the main menu, or BACK/CANCEL/DONE to close the current step.",
        ],
        "recommended_go": "Inventory, suppliers, product reports, and reminders make GO valuable for shops.",
        "recommended_pro": "PRO is best when staff record sales for the owner.",
    },
    "pharmacy": {
        "label": "Pharmacy / Medicine Store",
        "fit": "medicine sellers that need fast sales, stock awareness, suppliers, and customer balances",
        "basic_value": [
            "Record medicine sales and payments",
            "Record direct walk-in sales",
            "Track customer balances",
        ],
        "go_value": [
            "Inventory and low-stock awareness",
            "Supplier purchase/payment history",
            "Product and debt reports",
        ],
        "pro_value": [
            "Staff recording for attendants",
            "Permission control for records",
            "Owner-level dashboard across staff",
        ],
        "examples": [
            "Mary bought paracetamol 1500",
            "I sold 2 packs amoxicillin at 2500",
            "Ayo supplied 10 packs malaria drug at 1800 each",
        ],
        "quick_actions": [
            ("Record sale", "Send: Mary bought paracetamol 1500"),
            ("Direct sale", "Send: I sold 2 packs amoxicillin at 2500"),
            ("Stock", "Send: stock"),
            ("Supplier", "Send: suppliers"),
        ],
        "next_steps": [
            "After a sale is detected, confirm with YES or correct with EDIT.",
            "Use stock when you want to inspect inventory.",
            "Use suppliers when a supplier brings medicine or you pay them.",
            "Use MENU to see the main menu, or BACK to leave the current feature.",
        ],
        "recommended_go": "GO is strong for pharmacies because inventory and suppliers matter daily.",
        "recommended_pro": "PRO fits pharmacies with attendants or multiple people recording sales.",
    },
    "school": {
        "label": "School / Education",
        "fit": "schools, lessons, creche, and training centers tracking fees and balances",
        "basic_value": [
            "Record school fee payments",
            "Track student/parent balances",
            "View unpaid fee records",
        ],
        "go_value": [
            "Debt reminders for unpaid fees",
            "Better reports by period",
            "Notes on student/parent transactions",
        ],
        "pro_value": [
            "Admin/bursar staff access",
            "Permission control for staff",
            "Owner dashboard across all records",
        ],
        "examples": [
            "Tunde paid school fees 50000",
            "Aisha balance 20000 due Friday",
            "customer summary Aisha",
        ],
        "quick_actions": [
            ("Record fee", "Send: Tunde paid school fees 50000"),
            ("Set due balance", "Send: Aisha balance 20000 due Friday"),
            ("Student account", "Send: customer summary Aisha"),
            ("Debtors", "Send: unpaid debtors"),
        ],
        "next_steps": [
            "After recording a fee, confirm with YES or send EDIT.",
            "Use customer summary plus the student/parent name to review account history.",
            "Use due or unpaid debtors to follow balances.",
            "Use MENU to see the main menu, or BACK/DONE to leave the current flow.",
        ],
        "recommended_go": "GO adds reminders and stronger reports for unpaid fees.",
        "recommended_pro": "PRO fits schools where a bursar or admin staff records payments.",
    },
    "salon_beauty": {
        "label": "Salon / Beauty",
        "fit": "hair, barbing, nails, makeup, spa, and beauty product businesses",
        "basic_value": [
            "Record service income",
            "Record customer part-payment and balances",
            "See daily sales",
        ],
        "go_value": [
            "Debt reminders for unpaid service balances",
            "Notes and stronger reports",
            "Inventory for beauty products where needed",
        ],
        "pro_value": [
            "Staff/stylist recording",
            "Owner sees staff records",
            "Permission control",
        ],
        "examples": [
            "Blessing did braids 15000 paid 10000",
            "I received 3000 for haircut",
            "today sales",
        ],
        "quick_actions": [
            ("Record service", "Send: Blessing did braids 15000 paid 10000"),
            ("Direct income", "Send: I received 3000 for haircut"),
            ("Today sales", "Send: today sales"),
            ("Customer account", "Send: customer summary Blessing"),
        ],
        "next_steps": [
            "For direct income, confirm service income when prompted.",
            "For part-payment, confirm the balance before saving.",
            "Use today sales to see daily performance.",
            "Use MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO helps with reports, notes, reminders, and beauty product stock.",
        "recommended_pro": "PRO fits salons with stylists or attendants recording work.",
    },
    "artisan_services": {
        "label": "Artisan / Services",
        "fit": "tailors, mechanics, repairers, laundry, carpenters, and service providers",
        "basic_value": [
            "Record service income",
            "Record customer jobs and part-payments",
            "Track balances by customer",
        ],
        "go_value": [
            "Debt reminders for unpaid jobs",
            "Transaction notes and better reports",
            "Supplier/material records where useful",
        ],
        "pro_value": [
            "Workers/staff recording",
            "Permission control",
            "Owner view of all jobs and payments",
        ],
        "examples": [
            "Aisha sewed dress 25000 paid 15000",
            "I received 1000 for doing chair",
            "customer summary Aisha",
        ],
        "quick_actions": [
            ("Record job", "Send: Aisha sewed dress 25000 paid 15000"),
            ("Direct income", "Send: I received 1000 for doing chair"),
            ("Customer account", "Send: customer summary Aisha"),
            ("Due balances", "Send: due"),
        ],
        "next_steps": [
            "If a payment could be income or old debt, choose option 1 or 2 when asked.",
            "Confirm with YES to save, or EDIT to correct.",
            "Use customer summary to see a job/customer history.",
            "Use back, cancel, or menu when you are done.",
        ],
        "recommended_go": "GO adds reminders, notes, and better service/customer reports.",
        "recommended_pro": "PRO is useful when apprentices or workers record jobs for the owner.",
    },
    "food_hospitality": {
        "label": "Food / Hospitality",
        "fit": "restaurants, food vendors, bakeries, catering, bars, hotels, and frozen food sellers",
        "basic_value": [
            "Record food sales and customer payments",
            "Record direct daily sales",
            "See simple daily sales and customer balances",
        ],
        "go_value": [
            "Inventory for food items, drinks, or frozen stock",
            "Supplier purchases and supplier balances",
            "Product reports and debt reminders",
        ],
        "pro_value": [
            "Staff/cashier recording",
            "Owner view across attendants",
            "Permission control for team records",
        ],
        "examples": [
            "I sold 3 plates food at 2500",
            "Ade bought food 4000 paid 2000",
            "I buy 10 cartons drinks from Ayo at 5000 each",
        ],
        "quick_actions": [
            ("Record sale", "Send: I sold 3 plates food at 2500"),
            ("Customer balance", "Send: Ade bought food 4000 paid 2000"),
            ("Stock", "Send: stock"),
            ("Today sales", "Send: today sales"),
        ],
        "next_steps": [
            "For direct sales, confirm with YES or correct with EDIT.",
            "Use stock when you track drinks, frozen food, ingredients, or products.",
            "Use today sales to review daily income.",
            "Use MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO helps food businesses with stock, suppliers, product reports, and reminders.",
        "recommended_pro": "PRO fits restaurants, hotels, or food shops with attendants or cashiers.",
    },
    "agriculture": {
        "label": "Agriculture",
        "fit": "feed sellers, farms, produce traders, agrochemical sellers, livestock sellers, and cooperatives",
        "basic_value": [
            "Record sales and customer payments",
            "Track customer balances",
            "See simple sales reports",
        ],
        "go_value": [
            "Inventory for feed, produce, livestock, or agro products",
            "Supplier purchases and supplier balances",
            "Product reports and debt reminders",
        ],
        "pro_value": [
            "Staff/field worker recording",
            "Owner view across workers",
            "Permission control for team records",
        ],
        "examples": [
            "Ayo bought 5 bags feed at 18000",
            "I buy 20 bags feed from supplier at 15000 each",
            "stock",
        ],
        "quick_actions": [
            ("Record sale", "Send: Ayo bought 5 bags feed at 18000"),
            ("Supplier purchase", "Send: I buy 20 bags feed from supplier at 15000 each"),
            ("Stock", "Send: stock"),
            ("Debtors", "Send: unpaid debtors"),
        ],
        "next_steps": [
            "Confirm detected sales or purchases with YES, or send EDIT.",
            "Use stock to inspect quantity and value.",
            "Use suppliers when buying feed, produce, animals, or farm inputs.",
            "Use MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO is valuable for agriculture because stock, suppliers, and credit sales are common.",
        "recommended_pro": "PRO helps when workers or sales attendants record for the owner.",
    },
    "transport_logistics": {
        "label": "Transport / Logistics",
        "fit": "dispatch, logistics, car hire, truck supply, fleet, taxi, keke, and delivery businesses",
        "basic_value": [
            "Record delivery or trip income",
            "Track customer balances",
            "See simple daily reports",
        ],
        "go_value": [
            "Better reports by period",
            "Debt reminders for unpaid trips or deliveries",
            "Transaction notes for trip or delivery details",
        ],
        "pro_value": [
            "Driver/rider staff recording",
            "Owner view across drivers or riders",
            "Permission control for team records",
        ],
        "examples": [
            "I received 2500 for delivery",
            "Bola delivery 6000 paid 4000",
            "today sales",
        ],
        "quick_actions": [
            ("Record income", "Send: I received 2500 for delivery"),
            ("Customer balance", "Send: Bola delivery 6000 paid 4000"),
            ("Today sales", "Send: today sales"),
            ("Customer account", "Send: customer summary Bola"),
        ],
        "next_steps": [
            "For direct delivery income, confirm with YES or correct with EDIT.",
            "For unpaid trips, use customer summary to review the account.",
            "Use due to follow unpaid delivery or hire balances.",
            "Use MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO adds stronger reports, reminders, and notes for trips or delivery balances.",
        "recommended_pro": "PRO fits logistics or fleets where drivers/riders record work.",
    },
    "real_estate_rentals": {
        "label": "Real Estate / Rentals",
        "fit": "property managers, estate agents, short-lets, shop rent, equipment rental, and event rental",
        "basic_value": [
            "Record rent, booking, commission, or rental payments",
            "Track tenant/customer balances",
            "See unpaid balances",
        ],
        "go_value": [
            "Debt reminders for rent or rental balances",
            "Better reports by period",
            "Notes for property, unit, booking, or rental details",
        ],
        "pro_value": [
            "Staff/agent recording",
            "Owner view across agents or property staff",
            "Permission control for team records",
        ],
        "examples": [
            "Tenant A paid rent 200000",
            "Shop 4 balance 50000 due Friday",
            "unpaid debtors",
        ],
        "quick_actions": [
            ("Record payment", "Send: Tenant A paid rent 200000"),
            ("Set balance", "Send: Shop 4 balance 50000 due Friday"),
            ("Debtors", "Send: unpaid debtors"),
            ("Account history", "Send: customer summary Tenant A"),
        ],
        "next_steps": [
            "After recording rent or rental payment, confirm with YES or send EDIT.",
            "Use due or unpaid debtors to follow balances.",
            "Use customer summary for tenant, shop, property, or renter history.",
            "Use MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO adds reminders, notes, and better reports for rent and rental balances.",
        "recommended_pro": "PRO fits agencies or managers with staff/agents recording payments.",
    },
    "professional_services": {
        "label": "Professional / Office Services",
        "fit": "printing, business centers, bookkeeping, law chambers, consulting, and cleaning services",
        "basic_value": [
            "Record service income",
            "Track customer balances",
            "See simple sales reports",
        ],
        "go_value": [
            "Transaction notes for service details",
            "Better reports by period",
            "Debt reminders for unpaid service balances",
        ],
        "pro_value": [
            "Staff recording",
            "Owner view across staff records",
            "Permission control for team records",
        ],
        "examples": [
            "I received 3000 for printing",
            "Ayo printed flyers 15000 paid 10000",
            "today sales",
        ],
        "quick_actions": [
            ("Record income", "Send: I received 3000 for printing"),
            ("Customer balance", "Send: Ayo printed flyers 15000 paid 10000"),
            ("Today sales", "Send: today sales"),
            ("Customer account", "Send: customer summary Ayo"),
        ],
        "next_steps": [
            "For direct service income, confirm with YES or correct with EDIT.",
            "For part-payment, confirm the balance before saving.",
            "Use customer summary to review service/customer history.",
            "Use MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO adds notes, reports, and reminders for service balances.",
        "recommended_pro": "PRO helps offices where staff record jobs or payments for the owner.",
    },
    "thrift_contribution": {
        "label": "Thrift / Contributions",
        "fit": "thrift collectors, ajo/esusu groups, daily contribution, savings groups, and cooperative savings",
        "basic_value": [
            "Track up to 10 participants",
            "Record contribution amounts",
            "View basic participant balances",
        ],
        "go_value": [
            "Unlimited participants",
            "Contribution reminders",
            "Participant contribution history",
        ],
        "pro_value": [
            "Staff/collector recording",
            "Owner view across collectors",
            "Permission control for contribution records",
        ],
        "examples": [
            "Amina contributed 5000",
            "Tunde paid thrift 2000",
            "customer summary Amina",
        ],
        "quick_actions": [
            ("Record contribution", "Send: Amina contributed 5000"),
            ("Participant payment", "Send: Tunde paid thrift 2000"),
            ("Participant history", "Send: customer summary Amina"),
            ("Reminders", "Send: due"),
        ],
        "next_steps": [
            "Add participants like customers, then record each contribution.",
            "Confirm with YES to save, or EDIT to correct.",
            "Use customer summary to see a participant history.",
            "Use due for contribution reminders. Send MENU for the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO removes the 10-participant BASIC limit and adds reminders plus participant history.",
        "recommended_pro": "PRO helps thrift businesses with staff or collectors recording contributions.",
    },
    "energy_fuel": {
        "label": "Energy & Fuel",
        "fit": "fuel stations, kerosene/diesel sellers, LPG dealers, and petroleum marketers tracking litres, cylinders, and bulk sales",
        "basic_value": [
            "Record fuel and product sales",
            "Track customer credit and balances",
            "Record direct pump/counter sales",
        ],
        "go_value": [
            "Stock tracking by litre, cylinder, or drum",
            "Depot/supplier purchase records",
            "Product and profit reports",
        ],
        "pro_value": [
            "Staff recording for pump attendants",
            "Permission control per attendant",
            "Owner dashboard across all pumps and staff",
        ],
        "examples": [
            "I sold 200 liters petrol at 750",
            "Ade bought diesel 100 liters at 1200 paid 80000",
            "depot supplied 10000 liters PMS at 700 each",
        ],
        "quick_actions": [
            ("Record sale", "Send: I sold 200 liters petrol at 750"),
            ("Customer credit", "Send: Ade bought diesel 100 liters at 1200 paid 80000"),
            ("Stock", "Send: stock"),
            ("Dashboard", "Send: dashboard"),
        ],
        "next_steps": [
            "After a sale is detected, confirm with YES or correct with EDIT.",
            "Send stock to check fuel or product levels.",
            "Send suppliers to track depot purchases and balances.",
            "Send MENU to see the main menu, or BACK/CANCEL/DONE to close the current step.",
        ],
        "recommended_go": "GO is valuable for fuel businesses needing stock tracking, depot supplier records, and product reports.",
        "recommended_pro": "PRO fits stations with attendants or multiple pumps recording sales.",
    },
    "quarry_raw_materials": {
        "label": "Quarry & Raw Materials",
        "fit": "sand sellers, granite/gravel suppliers, quarry owners, and block makers tracking trips, tonnes, and bulk deliveries",
        "basic_value": [
            "Record bulk material sales by trip, tonne, or load",
            "Track customer credit and site balances",
            "Record direct cash sales",
        ],
        "go_value": [
            "Stock tracking by trip, tonne, or crate",
            "Supplier and haulage records",
            "Customer debt reports and reminders",
        ],
        "pro_value": [
            "Staff and driver recording",
            "Control what drivers can record",
            "Owner-level dashboard across sites and staff",
        ],
        "examples": [
            "I sold 5 trips sand to Bayo at 35000",
            "Ade bought 10 tonnes granite at 8000 paid 50000",
            "Ade bought 500 blocks at 200 each",
        ],
        "quick_actions": [
            ("Record sale", "Send: I sold 5 trips sand to Bayo at 35000"),
            ("Customer credit", "Send: Ade bought 10 tonnes granite at 8000 paid 50000"),
            ("Stock", "Send: stock"),
            ("Dashboard", "Send: dashboard"),
        ],
        "next_steps": [
            "After a sale is detected, confirm with YES or correct with EDIT.",
            "Send stock to check material levels.",
            "Send dashboard to see sales, debtors, and totals.",
            "Send MENU to see the main menu, or BACK/CANCEL/DONE to close the current step.",
        ],
        "recommended_go": "GO adds inventory tracking, supplier records, and debt reminders — important for bulk material businesses with many site customers.",
        "recommended_pro": "PRO fits quarries and block makers with multiple drivers or workers recording deliveries.",
    },
}


RECEIPT_CONFIG = {
    "retail_trading": {
        "title": "Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you for your business.",
    },
    "pharmacy": {
        "title": "Pharmacy Receipt",
        "customer_label": "Patient",
        "amount_label": "Total",
        "footer": "Keep this receipt for reference.",
    },
    "school": {
        "title": "Fee Payment Receipt",
        "customer_label": "Student",
        "amount_label": "Amount",
        "footer": "Please keep this receipt as proof of payment.",
    },
    "salon_beauty": {
        "title": "Service Receipt",
        "customer_label": "Client",
        "amount_label": "Total",
        "footer": "Thank you for visiting us.",
    },
    "artisan_services": {
        "title": "Work Receipt",
        "customer_label": "Client",
        "amount_label": "Total",
        "footer": "Thank you for your patronage.",
    },
    "food_hospitality": {
        "title": "Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you, come again!",
    },
    "agriculture": {
        "title": "Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you for your business.",
    },
    "transport_logistics": {
        "title": "Trip / Delivery Receipt",
        "customer_label": "Customer",
        "amount_label": "Amount",
        "footer": "Thank you for choosing us.",
    },
    "real_estate_rentals": {
        "title": "Payment Receipt",
        "customer_label": "Tenant",
        "amount_label": "Amount",
        "footer": "Please keep this receipt as proof of payment.",
    },
    "professional_services": {
        "title": "Invoice / Receipt",
        "customer_label": "Client",
        "amount_label": "Total",
        "footer": "Thank you for your patronage.",
    },
    "thrift_contribution": {
        "title": "Contribution Receipt",
        "customer_label": "Participant",
        "amount_label": "Amount",
        "footer": "Thank you for your contribution.",
    },
    "energy_fuel": {
        "title": "Sales Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you for your business.",
    },
    "quarry_raw_materials": {
        "title": "Delivery Receipt",
        "customer_label": "Customer / Site",
        "amount_label": "Total",
        "footer": "Thank you for your business.",
    },
}

DEFAULT_RECEIPT_CONFIG = {
    "title": "Receipt",
    "customer_label": "Customer",
    "amount_label": "Total",
    "footer": "Thank you for your business.",
}


def receipt_config_for_user(user):
    """Return the niche-specific receipt config for a business owner."""
    key = template_key_for_user(user)
    return RECEIPT_CONFIG.get(key, DEFAULT_RECEIPT_CONFIG)


def business_category_by_key(key):
    for category in BUSINESS_CATEGORIES:
        if category["key"] == key:
            return category
    return None


def selected_business_category(text):
    normalized = (text or "").lower().strip()
    for index, category in enumerate(BUSINESS_CATEGORIES, start=1):
        if normalized in [str(index), category["key"], category["label"].lower()]:
            return category
    return None


def selected_business_type(category, text):
    normalized = (text or "").lower().strip()
    for index, (key, label) in enumerate(category["businesses"], start=1):
        if normalized in [str(index), key, label.lower()]:
            return key, label
    return None, None


def make_custom_business_key(label):
    clean = re.sub(r"[^a-z0-9]+", "_", (label or "").lower()).strip("_")
    return clean[:60] or "custom_business"


def build_business_category_menu():
    lines = [
        "What category best describes your business?\n",
        "Choose one number. This helps CreditVoice show the right examples, reports, and next steps.\n",
    ]
    for index, category in enumerate(BUSINESS_CATEGORIES, start=1):
        lines.append(f"{index}. {category['label']}")
    lines.append("\nReply with the number. Choose Other if you do not see your type.")
    return "\n".join(lines)


def build_business_type_menu(category):
    lines = [
        f"{category['label']}\n",
        "Pick the closest business type. You can choose Other if none fits.\n",
    ]
    for index, (_, label) in enumerate(category["businesses"], start=1):
        lines.append(f"{index}. {label}")
    lines.append("\nReply with the number. Send back to return to categories.")
    return "\n".join(lines)


def business_type_display(user):
    label = getattr(user, "business_type_label", None)
    if label:
        return label
    category = business_category_by_key(getattr(user, "business_category", None))
    return category["label"] if category else "General Business"


def template_key_for_user(user):
    business_type = getattr(user, "business_type", None)
    if business_type in BUSINESS_TEMPLATE_ALIASES:
        return BUSINESS_TEMPLATE_ALIASES[business_type]

    category = getattr(user, "business_category", None)
    if category == "retail_trading":
        return "retail_trading"
    if category == "health":
        return "pharmacy"
    if category == "education":
        return "school"
    if category == "beauty_personal_care":
        return "salon_beauty"
    if category == "services_artisans":
        return "artisan_services"
    if category == "food_hospitality":
        return "food_hospitality"
    if category == "agriculture":
        return "agriculture"
    if category == "transport_logistics":
        return "transport_logistics"
    if category == "real_estate_rentals":
        return "real_estate_rentals"
    if category == "professional_office_services":
        return "professional_services"
    if category == "thrift_contribution":
        return "thrift_contribution"
    return None


def industry_template_for_user(user):
    key = template_key_for_user(user)
    if key:
        return INDUSTRY_TEMPLATES.get(key)
    return None


def template_examples_for_user(user):
    template = industry_template_for_user(user)
    if template:
        return template["examples"]

    business_type = getattr(user, "business_type", None)
    examples = INDUSTRY_EXAMPLES.get(business_type)
    if examples:
        return examples

    category = getattr(user, "business_category", None)
    if category == "education":
        return [
            "Tunde paid school fees 50000",
            "Aisha balance 20000 due Friday",
            "dashboard",
        ]
    if category == "health":
        return [
            "Mary bought medicine 1500",
            "I sold 2 packs drugs at 2500",
            "stock",
        ]
    if category == "beauty_personal_care":
        return [
            "Blessing did hair 15000 paid 10000",
            "I received 3000 for service",
            "today sales",
        ]
    if category == "food_hospitality":
        return [
            "I sold food 2500",
            "Ade bought food 4000 paid 2000",
            "today sales",
        ]
    return [
        "Ade bought rice 5000",
        "Ade paid 3000",
        "dashboard",
    ]


def template_quick_actions_for_user(user):
    template = industry_template_for_user(user)
    if template:
        return template["quick_actions"]
    return [
        ("Record sale", "Send: Ade bought rice 5000"),
        ("Record payment", "Send: Ade paid 3000"),
        ("Dashboard", "Send: dashboard"),
        ("Formats", "Send: formats"),
    ]


def template_next_steps_for_user(user):
    template = industry_template_for_user(user)
    if template:
        return template["next_steps"]
    return [
        "Confirm with YES to save or EDIT to correct.",
        "Send dashboard to review your business.",
        "Send formats when you need examples.",
        "Send MENU to see the main menu, or BACK/CANCEL/DONE to close the current flow.",
    ]


def template_plan_value_for_user(user):
    template = industry_template_for_user(user)
    if not template:
        return {
            "basic": [
                "Record sales, payments, and balances",
                "Use direct sale",
                "View simple business reports",
            ],
            "go": [
                "Unlimited customers and transactions",
                "Inventory, suppliers, reminders, and notes where needed",
                "Better reports",
            ],
            "pro": [
                "Staff access",
                "Staff permissions",
                "Owner view across staff records",
            ],
        }
    return {
        "basic": template["basic_value"],
        "go": template["go_value"],
        "pro": template["pro_value"],
        "go_reason": template["recommended_go"],
        "pro_reason": template["recommended_pro"],
    }


def industry_plan_matrix():
    matrix = {}
    for key in HIGH_VALUE_TEMPLATE_KEYS:
        template = INDUSTRY_TEMPLATES[key]
        matrix[key] = {
            "label": template["label"],
            "basic": template["basic_value"],
            "go": template["go_value"],
            "pro": template["pro_value"],
            "go_reason": template["recommended_go"],
            "pro_reason": template["recommended_pro"],
        }
    return matrix
