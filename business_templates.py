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
            ("kitchen_utensils", "Kitchen Utensils / Cookware"),
            ("hardware_store", "Hardware / Building Materials Shop"),
            ("household_goods", "Household Goods Shop"),
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

PARTIAL_SUPPORT_TYPES = {
    "hotel_guest_house": {
        "label": "Hotel / Guest House",
        "works": "Track guest bills, payments, and outstanding balances",
        "missing": "Room booking, availability management, and check-in/check-out",
    },
    "property_manager": {
        "label": "Property Manager",
        "works": "Track rent payments and outstanding balances per tenant",
        "missing": "Property listings, lease contracts, and unit management",
    },
    "estate_agent": {
        "label": "Estate Agent",
        "works": "Track client payments and outstanding balances",
        "missing": "Property listings, commissions workflow, and deal tracking",
    },
    "clinic": {
        "label": "Clinic",
        "works": "Track patient bills, consultation fees, and outstanding balances",
        "missing": "Patient records, prescriptions, and clinical management",
    },
    "dental_clinic": {
        "label": "Dental Clinic",
        "works": "Track patient bills and outstanding fee balances",
        "missing": "Patient records, treatment history, and clinical notes",
    },
    "eye_clinic": {
        "label": "Eye Clinic",
        "works": "Track patient bills and outstanding fee balances",
        "missing": "Patient records, prescription notes, and frame/lens stock by patient",
    },
    "laboratory": {
        "label": "Laboratory / Test Center",
        "works": "Track patient bills and outstanding balances",
        "missing": "Test result records, sample tracking, and patient referrals",
    },
}

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
    "clinic": [
        "Bayo paid consultation fee 5000",
        "Aisha lab test 8000 paid 5000",
        "customer summary Aisha",
    ],
    "dental_clinic": [
        "Bayo tooth extraction 8000 paid 5000",
        "Aisha dental checkup 3000",
        "customer summary Bayo",
    ],
    "eye_clinic": [
        "Bayo eye test 3000",
        "Aisha glasses fitting 15000 paid 10000",
        "customer summary Bayo",
    ],
    "laboratory": [
        "Bayo malaria test 3500",
        "Aisha blood test 2500",
        "customer summary Bayo",
    ],
    "hotel_guest_house": [
        "Bola room 2 nights 30000 paid 20000",
        "Ade room balance 15000 due Friday",
        "customer summary Bola",
    ],
    "beauty_products": [
        "Blessing bought relaxer 3500",
        "I sold 2 packs shampoo at 2500",
        "stock",
    ],
    "bookkeeping": [
        "Bayo paid accounting fee 25000",
        "Ade audit 50000 paid 30000",
        "customer summary Bayo",
    ],
    "law_chamber": [
        "Bayo paid legal fee 50000",
        "Ade case 100000 paid 50000",
        "customer summary Bayo",
    ],
    "consulting": [
        "Bayo paid consulting fee 80000",
        "Ade project 150000 paid 50000",
        "customer summary Bayo",
    ],
    "cleaning_service": [
        "Bayo 5 offices cleaning 20000 paid 15000",
        "I received 8000 for house cleaning",
        "customer summary Bayo",
    ],
    "electrician": [
        "Bayo wiring job 15000 paid 10000",
        "I received 5000 for electrical work",
        "customer summary Bayo",
    ],
    "plumber": [
        "Bayo plumbing repair 8000 paid 5000",
        "I received 6000 for pipe fitting",
        "customer summary Bayo",
    ],
    "carpentry_furniture": [
        "Bayo wardrobe 45000 paid 20000",
        "I received 8000 for door installation",
        "customer summary Bayo",
    ],
    "phone_repair": [
        "Bayo phone screen 12000 paid 10000",
        "I received 5000 for iPhone repair",
        "customer summary Bayo",
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
    "kitchen_utensils": "household_hardware",
    "hardware_store": "household_hardware",
    "household_goods": "household_hardware",
    "pharmacy": "pharmacy",
    "patent_medicine": "pharmacy",
    "clinic": "clinic",
    "dental_clinic": "clinic",
    "eye_clinic": "clinic",
    "laboratory": "clinic",
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
    "laundry_dry_cleaning": "laundry",
    "car_wash":             "car_wash",
    "tailor_fashion":       "tailor",
    "barbing_salon":        "barber",
    "mechanic":             "mechanic",
    "electrician": "artisan_services",
    "plumber": "artisan_services",
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
    "household_hardware": {
        "label": "Kitchen / Hardware / Household",
        "fit": "sellers of cookware, hardware items, household goods, and building materials",
        "basic_value": [
            "Record customer sales and payments",
            "Record walk-in counter sales",
            "Track customer balances and debts",
        ],
        "go_value": [
            "Full inventory — pots, pans, hardware, fittings",
            "Supplier purchases and supplier debt",
            "Product sales reports",
        ],
        "pro_value": [
            "Staff recording for shop attendants",
            "Permission control per staff member",
            "Owner-level dashboard across all staff",
        ],
        "examples": [
            "Bello bought 2 pots at 3500 paid 2000",
            "I sold 1 frying pan at 2800",
            "I buy 10 dozen plates from Ayo at 4500 each",
        ],
        "quick_actions": [
            ("Record sale", "Send: Bello bought pot 3500"),
            ("Check stock", "Send: stock"),
            ("Supplier", "Send: suppliers"),
            ("Dashboard", "Send: dashboard"),
        ],
        "next_steps": [
            "After saving a sale, reply YES to save or EDIT to correct it.",
            "Send stock to see inventory.",
            "Send dashboard to review sales, debtors, and top products.",
            "Send MENU to see the main menu.",
        ],
        "recommended_go": "GO is valuable for tracking which items move fastest and managing supplier debt.",
        "recommended_pro": "PRO is best when shop attendants record sales on behalf of the owner.",
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
        "fit": "electricians, plumbers, carpenters, phone repairers, and other service providers",
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
            "Bayo job 15000 paid 8000",
            "I received 5000 for repair work",
            "customer summary Bayo",
        ],
        "quick_actions": [
            ("Record job", "Send: Bayo job 15000 paid 8000"),
            ("Direct income", "Send: I received 5000 for repair work"),
            ("Customer account", "Send: customer summary Bayo"),
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
    "laundry": {
        "label": "Laundry / Dry Cleaning",
        "fit": "laundry and dry cleaning businesses tracking jobs, customer balances, and service prices",
        "basic_value": [
            "Set up your service price list (shirt, trouser, curtain, etc.)",
            "Record jobs: John brought 10 shirts, 5 trousers — auto-total",
            "Track customer balances and part-payments",
        ],
        "go_value": [
            "Debt reminders for unpaid laundry balances",
            "Better reports — daily jobs, top customers",
            "Transaction notes for job details",
        ],
        "pro_value": [
            "Staff recording for attendants",
            "Owner sees all staff records",
            "Permission control",
        ],
        "examples": [
            "John brought 10 shirts, 5 trousers, 2 curtains",
            "John paid 3000",
            "today sales",
        ],
        "quick_actions": [
            ("Record job", "Send: John brought 10 shirts, 5 trousers"),
            ("Record payment", "Send: John paid 3000"),
            ("Today jobs", "Send: today sales"),
            ("Customer account", "Send: customer summary John"),
        ],
        "next_steps": [
            "Set up your price list first — send: price list",
            "Record jobs by typing: [customer] brought [items]",
            "Confirm with YES to save, or EDIT to correct.",
            "Send MENU to see the main menu.",
        ],
        "recommended_go": "GO adds reminders for unpaid laundry balances and better reports.",
        "recommended_pro": "PRO fits laundries with attendants recording jobs for the owner.",
    },
    "car_wash": {
        "label": "Car Wash",
        "fit": "car wash businesses tracking jobs, service tiers, and customer balances",
        "basic_value": [
            "Set up your price list (body wash, full wash, engine wash, etc.)",
            "Record jobs: John brought car full wash — auto-total",
            "Track customer balances",
        ],
        "go_value": [
            "Debt reminders for unpaid balances",
            "Daily job reports",
            "Transaction notes for job details",
        ],
        "pro_value": [
            "Staff/washer recording",
            "Owner sees all staff records",
            "Permission control",
        ],
        "examples": [
            "John brought saloon car full wash",
            "Bayo brought jeep body wash, paid 2000",
            "today sales",
        ],
        "quick_actions": [
            ("Record job", "Send: John brought saloon car full wash"),
            ("Record payment", "Send: John paid 3000"),
            ("Today jobs", "Send: today sales"),
            ("Price list", "Send: price list"),
        ],
        "next_steps": [
            "Set up your price list first — send: price list",
            "Record jobs: [customer] brought [vehicle type] [service]",
            "Confirm with YES to save.",
            "Send MENU to see the main menu.",
        ],
        "recommended_go": "GO adds reminders and better daily job reports.",
        "recommended_pro": "PRO fits car washes with washers recording jobs.",
    },
    "barber": {
        "label": "Barbing Salon",
        "fit": "barbing salons tracking service income, customer balances, and price list",
        "basic_value": [
            "Set up service prices (haircut, shaving, kids cut, etc.)",
            "Record direct income fast",
            "Track customer balances",
        ],
        "go_value": [
            "Debt reminders for unpaid balances",
            "Daily and weekly sales reports",
            "Transaction notes",
        ],
        "pro_value": [
            "Staff barber recording",
            "Owner view across all barbers",
            "Permission control",
        ],
        "examples": [
            "I received 1500 for haircut and shaving",
            "Bayo got haircut 500 paid 0",
            "today sales",
        ],
        "quick_actions": [
            ("Direct income", "Send: I received 1500 for haircut"),
            ("Customer balance", "Send: Bayo haircut 500"),
            ("Today sales", "Send: today sales"),
            ("Price list", "Send: price list"),
        ],
        "next_steps": [
            "Set up your price list — send: price list",
            "For cash walk-ins: I received [amount] for [service]",
            "For balances: [name] [service] [amount]",
            "Send MENU to see the main menu.",
        ],
        "recommended_go": "GO adds reminders, notes, and better reports for the barbing salon.",
        "recommended_pro": "PRO fits salons with multiple barbers recording work.",
    },
    "tailor": {
        "label": "Tailor / Fashion Designer",
        "fit": "tailors and fashion designers tracking jobs, deposits, and customer balances",
        "basic_value": [
            "Record jobs with deposit and balance",
            "Set up service prices for common sewing jobs",
            "Track customer balances and due dates",
        ],
        "go_value": [
            "Debt reminders for unpaid job balances",
            "Better reports — jobs done, outstanding",
            "Transaction notes for fabric/design details",
        ],
        "pro_value": [
            "Staff/apprentice recording",
            "Owner view across workers",
            "Permission control",
        ],
        "examples": [
            "Aisha sewed dress 25000 paid 15000",
            "John brought 2 shirts, 1 trouser for sewing",
            "customer summary Aisha",
        ],
        "quick_actions": [
            ("Record job", "Send: Aisha sewed dress 25000 paid 15000"),
            ("Job with balance", "Send: Bayo suit 30000 paid 15000 due Friday"),
            ("Customer account", "Send: customer summary Aisha"),
            ("Price list", "Send: price list"),
        ],
        "next_steps": [
            "Record jobs: [customer] [item] sewed [amount] paid [deposit]",
            "Set up common sewing prices — send: price list",
            "Confirm with YES to save.",
            "Send MENU to see the main menu.",
        ],
        "recommended_go": "GO adds reminders and notes for fabrics and design details.",
        "recommended_pro": "PRO helps tailors with apprentices recording work.",
    },
    "mechanic": {
        "label": "Mechanic Workshop",
        "fit": "mechanics tracking jobs, labour charges, and customer balances",
        "basic_value": [
            "Record job income and customer balances",
            "Set up common labour price list",
            "Track unpaid balances",
        ],
        "go_value": [
            "Debt reminders for unpaid jobs",
            "Transaction notes for parts and job details",
            "Better reports",
        ],
        "pro_value": [
            "Staff/apprentice recording",
            "Owner view across workers",
            "Permission control",
        ],
        "examples": [
            "Bayo brought car oil change",
            "Ade car service 15000 paid 8000",
            "customer summary Bayo",
        ],
        "quick_actions": [
            ("Record job", "Send: Bayo brought car oil change"),
            ("Job with balance", "Send: Ade car service 15000 paid 8000"),
            ("Customer account", "Send: customer summary Bayo"),
            ("Price list", "Send: price list"),
        ],
        "next_steps": [
            "Set up labour prices — send: price list",
            "Record jobs: [customer] brought [vehicle] [service]",
            "Confirm with YES to save.",
            "Send MENU to see the main menu.",
        ],
        "recommended_go": "GO adds notes for parts, reminders, and better job reports.",
        "recommended_pro": "PRO fits workshops with apprentices recording jobs.",
    },
    "clinic": {
        "label": "Clinic / Health Service",
        "fit": "clinics, dental, eye, laboratories, and other health service businesses collecting consultation and procedure fees",
        "basic_value": [
            "Record consultation and procedure fee payments",
            "Track patient/client balances",
            "View unpaid fee records",
        ],
        "go_value": [
            "Debt reminders for unpaid medical fees",
            "Better reports by period",
            "Notes for patient/case details",
        ],
        "pro_value": [
            "Staff/receptionist recording",
            "Owner view across staff records",
            "Permission control for team records",
        ],
        "examples": [
            "Bayo paid consultation fee 5000",
            "Aisha lab test 8000 paid 5000",
            "customer summary Aisha",
        ],
        "quick_actions": [
            ("Record payment", "Send: Bayo paid consultation fee 5000"),
            ("Patient balance", "Send: Aisha lab test 8000 paid 5000"),
            ("Patient account", "Send: customer summary Aisha"),
            ("Debtors", "Send: unpaid debtors"),
        ],
        "next_steps": [
            "After recording a fee, confirm with YES or send EDIT.",
            "Use customer summary to see a patient account history.",
            "Use due or unpaid debtors to follow unpaid balances.",
            "Send MENU to see the main menu, or BACK/CANCEL to leave the current flow.",
        ],
        "recommended_go": "GO adds reminders for unpaid medical fees and better reports.",
        "recommended_pro": "PRO fits clinics with receptionists or staff recording payments.",
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
    "clinic": {
        "title": "Medical Receipt",
        "customer_label": "Patient",
        "amount_label": "Amount",
        "footer": "Please keep this receipt for your records.",
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
    "laundry": {
        "title": "Laundry Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you for choosing us. Your clothes are ready!",
    },
    "car_wash": {
        "title": "Car Wash Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you! Drive clean.",
    },
    "barber": {
        "title": "Service Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you for your patronage.",
    },
    "tailor": {
        "title": "Sewing Receipt",
        "customer_label": "Client",
        "amount_label": "Total",
        "footer": "Thank you for patronising us.",
    },
    "mechanic": {
        "title": "Workshop Receipt",
        "customer_label": "Customer",
        "amount_label": "Total",
        "footer": "Thank you for your patronage. Drive safely.",
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
    if business_type in ("kitchen_utensils", "hardware_store", "household_goods"):
        return "household_hardware"
    if category == "retail_trading":
        return "retail_trading"
    if category == "health":
        return "pharmacy"
    if category == "education":
        return "school"
    if category == "beauty_personal_care":
        return "salon_beauty"
    if category == "services_artisans":
        if business_type == "laundry_dry_cleaning":
            return "laundry"
        if business_type == "car_wash":
            return "car_wash"
        if business_type == "tailor_fashion":
            return "tailor"
        if business_type == "barbing_salon":
            return "barber"
        if business_type == "mechanic":
            return "mechanic"
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
    # Type-specific examples take priority over template defaults
    business_type = getattr(user, "business_type", None)
    if business_type:
        examples = INDUSTRY_EXAMPLES.get(business_type)
        if examples:
            return examples

    template = industry_template_for_user(user)
    if template:
        return template["examples"]

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


# ─────────────────────────────────────────────────────────────────────────────
# Industry product catalog — (product_canonical_name, category) pairs.
# Used to auto-assign categories to new inventory items and to build
# industry-specific stock-add guides.
# ─────────────────────────────────────────────────────────────────────────────

INDUSTRY_PRODUCT_CATALOG = {
    "clinic": [
        ("glove", "consumable"),
        ("syringe", "consumable"),
        ("needle", "consumable"),
        ("cotton wool", "consumable"),
        ("bandage", "consumable"),
        ("plaster", "consumable"),
        ("iv set", "consumable"),
        ("cannula", "consumable"),
        ("gauze", "consumable"),
        ("surgical spirit", "consumable"),
        ("paracetamol", "analgesic"),
        ("ibuprofen", "analgesic"),
        ("amoxicillin", "antibiotic"),
        ("metronidazole", "antibiotic"),
        ("coartem", "antimalarial"),
        ("ors", "rehydration"),
        ("gloves", "consumable"),
    ],
    "pharmacy": [
        ("paracetamol", "analgesic"),
        ("ibuprofen", "analgesic"),
        ("aspirin", "analgesic"),
        ("amoxicillin", "antibiotic"),
        ("ampicillin", "antibiotic"),
        ("metronidazole", "antibiotic"),
        ("coartem", "antimalarial"),
        ("artemether", "antimalarial"),
        ("chloroquine", "antimalarial"),
        ("vitamin c", "supplement"),
        ("vitamin b complex", "supplement"),
        ("zinc", "supplement"),
        ("cough syrup", "cough remedy"),
        ("piriton", "antihistamine"),
        ("loratadine", "antihistamine"),
        ("omeprazole", "antacid"),
        ("antacid", "antacid"),
        ("ors", "rehydration"),
        ("oral rehydration", "rehydration"),
        ("condom", "family planning"),
        ("glove", "consumable"),
        ("syringe", "consumable"),
        ("cotton wool", "consumable"),
        ("bandage", "consumable"),
        ("plaster", "consumable"),
        ("maggi", "common otc"),
        ("panadol", "analgesic"),
    ],
    "agriculture": [
        ("garri", "staple food"),
        ("rice", "staple food"),
        ("beans", "staple food"),
        ("yam", "staple food"),
        ("maize", "grain"),
        ("sorghum", "grain"),
        ("wheat", "grain"),
        ("groundnut", "seed & oil"),
        ("palm oil", "oil"),
        ("soybean", "seed & oil"),
        ("cassava", "tuber"),
        ("potato", "tuber"),
        ("tomato", "vegetable"),
        ("pepper", "vegetable"),
        ("onion", "vegetable"),
        ("plantain", "fruit"),
        ("banana", "fruit"),
        ("orange", "fruit"),
        ("egg", "poultry"),
        ("broiler", "poultry"),
        ("day old chick", "poultry"),
        ("catfish", "fish"),
        ("tilapia", "fish"),
        ("feed", "animal feed"),
        ("poultry feed", "animal feed"),
        ("fish feed", "animal feed"),
        ("fertilizer", "farm input"),
        ("pesticide", "farm input"),
        ("herbicide", "farm input"),
        ("fungicide", "farm input"),
    ],
    "retail_trading": [
        ("rice", "food"),
        ("garri", "food"),
        ("beans", "food"),
        ("sugar", "food"),
        ("salt", "food"),
        ("palm oil", "food"),
        ("noodles", "food"),
        ("indomie", "food"),
        ("tomato paste", "food"),
        ("maggi", "food"),
        ("biscuit", "snack"),
        ("bread", "bakery"),
        ("detergent", "cleaning"),
        ("soap", "cleaning"),
        ("bleach", "cleaning"),
        ("matches", "household"),
        ("candle", "household"),
        ("battery", "household"),
        ("toothpaste", "personal care"),
        ("toilet roll", "personal care"),
        ("tissue", "personal care"),
    ],
    "food_hospitality": [
        ("rice", "food"),
        ("beans", "food"),
        ("yam", "food"),
        ("plantain", "food"),
        ("chicken", "protein"),
        ("beef", "protein"),
        ("fish", "protein"),
        ("tomato", "vegetable"),
        ("pepper", "vegetable"),
        ("onion", "vegetable"),
        ("palm oil", "oil"),
        ("vegetable oil", "oil"),
        ("water", "beverage"),
        ("soft drink", "beverage"),
        ("beer", "beverage"),
        ("malt", "beverage"),
        ("bread", "bakery"),
        ("flour", "ingredient"),
        ("egg", "protein"),
    ],
    "energy_fuel": [
        ("petrol", "fuel"),
        ("pms", "fuel"),
        ("diesel", "fuel"),
        ("ago", "fuel"),
        ("kerosene", "fuel"),
        ("lpg", "gas"),
        ("cooking gas", "gas"),
        ("engine oil", "lubricant"),
        ("brake fluid", "lubricant"),
        ("gear oil", "lubricant"),
    ],
    "salon_beauty": [
        ("shampoo", "hair care"),
        ("conditioner", "hair care"),
        ("relaxer", "hair care"),
        ("hair color", "hair care"),
        ("hair cream", "hair care"),
        ("gel", "styling"),
        ("edge control", "styling"),
        ("weave", "hair extension"),
        ("wigs", "hair extension"),
        ("lace front", "hair extension"),
        ("nail polish", "nail care"),
        ("acrylic nail", "nail care"),
        ("foundation", "makeup"),
        ("lipstick", "makeup"),
        ("mascara", "makeup"),
        ("moisturizer", "skin care"),
        ("serum", "skin care"),
        ("sunscreen", "skin care"),
        ("manicure set", "tool"),
        ("hair dryer", "tool"),
    ],
    "quarry_raw_materials": [
        ("sand", "aggregate"),
        ("sharp sand", "aggregate"),
        ("granite", "aggregate"),
        ("gravel", "aggregate"),
        ("laterite", "soil"),
        ("block", "building material"),
        ("cement", "binding material"),
        ("stone", "aggregate"),
        ("clay", "raw material"),
    ],
    "household_hardware": [
        # Kitchen & cookware
        ("pot", "cookware"),
        ("frying pan", "cookware"),
        ("cooking spoon", "cookware"),
        ("spatula", "cookware"),
        ("kettle", "cookware"),
        ("pressure cooker", "cookware"),
        ("plates", "tableware"),
        ("cups", "tableware"),
        ("bowls", "tableware"),
        ("cutlery set", "tableware"),
        ("tray", "tableware"),
        ("flask", "tableware"),
        # Household & storage
        ("bucket", "household"),
        ("basin", "household"),
        ("cooler", "household"),
        ("water dispenser", "household"),
        ("broom", "household"),
        ("mop", "household"),
        ("dustbin", "household"),
        ("lantern", "household"),
        ("torch", "household"),
        ("fan", "electrical"),
        ("extension box", "electrical"),
        # Hardware & building
        ("padlock", "hardware"),
        ("nail", "hardware"),
        ("hinge", "hardware"),
        ("paint", "building materials"),
        ("plank", "building materials"),
        ("tile", "building materials"),
        ("cement", "building materials"),
        ("wire", "hardware"),
        ("pipe", "plumbing"),
        ("tap", "plumbing"),
    ],
}

# Preferred units per industry — shown in stock-add guides and as hints
INDUSTRY_DEFAULT_UNITS = {
    "pharmacy": ["pack", "strip", "tablet", "sachet", "bottle", "vial"],
    "clinic":   ["piece", "pack", "vial", "bottle", "sachet", "roll"],
    "agriculture": ["bag", "mudu", "congo", "crate", "tray", "kg"],
    "retail_trading": ["carton", "bag", "pack", "piece", "dozen"],
    "household_hardware": ["piece", "set", "dozen", "carton", "pack"],
    "food_hospitality": ["kg", "litre", "carton", "pack", "piece"],
    "energy_fuel": ["litre", "drum", "cylinder", "kg"],
    "salon_beauty": ["piece", "bottle", "pack", "set"],
    "quarry_raw_materials": ["trip", "tonne", "load", "truck load"],
    "thrift_contribution": [],
    "school": [],
    "artisan_services": [],
    "transport_logistics": [],
    "real_estate_rentals": [],
    "professional_services": [],
}


# ─────────────────────────────────────────────────────────────────────────────
# Service price catalog — (item_name, tier_label_or_None, default_price)
# Used to seed a service business's price list during guided setup.
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_PRICE_CATALOG = {
    "laundry": [
        ("shirt",         "wash & iron",  800),
        ("shirt",         "iron only",    400),
        ("trouser",       "wash & iron",  1000),
        ("trouser",       "iron only",    500),
        ("dress",         "wash & iron",  1200),
        ("dress",         "iron only",    600),
        ("blouse",        "wash & iron",  800),
        ("blouse",        "iron only",    400),
        ("jeans",         "wash & iron",  1000),
        ("jeans",         "iron only",    500),
        ("skirt",         "wash & iron",  800),
        ("skirt",         "iron only",    400),
        ("suit",          "wash & iron",  3000),
        ("suit",          "iron only",    1500),
        ("agbada",        "wash & iron",  4000),
        ("agbada",        "iron only",    2000),
        ("senator",       "wash & iron",  2000),
        ("senator",       "iron only",    1000),
        ("bed spread",    "wash & iron",  2500),
        ("bed spread",    "iron only",    1200),
        ("curtain",       "wash & iron",  1500),
        ("curtain",       "iron only",    800),
        ("duvet",         None,           3500),
        ("pillow case",   "wash & iron",  300),
        ("towel",         None,           500),
        ("baby clothes",  "wash & iron",  800),
        ("jacket",        "wash & iron",  1500),
        ("jacket",        "iron only",    700),
    ],
    "car_wash": [
        ("saloon car",    "body only",                      2000),
        ("saloon car",    "body + interior",                4000),
        ("saloon car",    "full (body + interior + engine)", 7000),
        ("jeep / SUV",    "body only",                      3000),
        ("jeep / SUV",    "body + interior",                5000),
        ("jeep / SUV",    "full (body + interior + engine)", 9000),
        ("bus / van",     "body only",                      3500),
        ("bus / van",     "body + interior",                6000),
        ("engine wash",   None,                             3500),
        ("interior cleaning", None,                         2500),
        ("bike wash",     None,                             500),
        ("tricycle wash", None,                             800),
    ],
    "barber": [
        ("haircut",           None,  500),
        ("low cut",           None,  500),
        ("shaving",           None,  300),
        ("barbing & shaving", None,  800),
        ("kids cut",          None,  400),
        ("hair treatment",    None,  1500),
        ("lining",            None,  200),
        ("mohawk",            None,  1000),
        ("dyeing",            None,  2000),
    ],
    "tailor": [
        ("shirt sewing",       None,  2500),
        ("trouser sewing",     None,  2500),
        ("skirt sewing",       None,  2000),
        ("dress sewing",       None,  4000),
        ("kaftan sewing",      None,  3000),
        ("ankara top sewing",  None,  2500),
        ("agbada sewing",      None,  8000),
        ("suit sewing",        None,  10000),
        ("alteration",         None,  1000),
        ("zip fixing",         None,  500),
        ("button fixing",      None,  200),
        ("hemming",            None,  500),
    ],
    "mechanic": [
        ("engine oil change",  "labour only",  2000),
        ("tyre change",        "per tyre",     500),
        ("brake pad change",   "front axle",   3000),
        ("brake pad change",   "rear axle",    3000),
        ("battery check",      None,           500),
        ("wheel balancing",    "per tyre",     500),
        ("wheel alignment",    None,           3000),
        ("vehicle diagnostic", None,           2000),
        ("AC service",         None,           5000),
        ("suspension repair",  None,           5000),
    ],
    "electrician": [
        ("fault finding",              None,           2000),
        ("socket replacement",         None,           1500),
        ("light fitting installation", None,           1000),
        ("ceiling fan installation",   None,           3000),
        ("wiring",                     "per point",    500),
        ("rewiring",                   "per room",     8000),
        ("generator connection",       None,           5000),
        ("stabilizer installation",    None,           3000),
        ("DSTV installation",          None,           3000),
        ("general inspection",         None,           2000),
    ],
    "plumber": [
        ("fault finding",              None,           2000),
        ("pipe fitting",               "per joint",    500),
        ("tap repair / replacement",   None,           2500),
        ("toilet repair",              None,           3500),
        ("wash hand basin install",    None,           5000),
        ("water tank installation",    None,           8000),
        ("drain clearing",             None,           4000),
        ("water pump installation",    None,           6000),
        ("general plumbing check",     None,           2000),
    ],
    "carpentry_furniture": [
        ("door installation",          None,           15000),
        ("door frame",                 None,           8000),
        ("window frame",               None,           10000),
        ("shelf installation",         None,           6000),
        ("wardrobe",                   "standard",     50000),
        ("wardrobe",                   "fitted",       80000),
        ("bed frame",                  None,           25000),
        ("ceiling board",              "per sqm",      2500),
        ("kitchen cabinet",            None,           60000),
        ("general repair",             None,           5000),
    ],
    "phone_repair": [
        ("screen replacement",         "Android",      8000),
        ("screen replacement",         "iPhone",       15000),
        ("battery replacement",        "Android",      5000),
        ("battery replacement",        "iPhone",       8000),
        ("charging port repair",       None,           4000),
        ("software fix / flash",       None,           3000),
        ("water damage repair",        None,           10000),
        ("camera repair",              None,           6000),
        ("speaker repair",             None,           3000),
        ("button repair",              None,           2000),
        ("back glass replacement",     None,           5000),
    ],
    "clinic": [
        ("consultation",              None,           3000),
        ("malaria test (RDT)",        None,           2000),
        ("blood count (FBC)",         None,           4000),
        ("urinalysis",                None,           2000),
        ("pregnancy test",            None,           1500),
        ("blood pressure check",      None,           1000),
        ("blood glucose test",        None,           1500),
        ("typhoid test (Widal)",      None,           2500),
        ("hepatitis B test",          None,           2500),
        ("HIV test",                  None,           2000),
        ("injection",                 None,           2000),
        ("IV drip",                   None,           5000),
        ("wound dressing",            None,           2500),
        ("circumcision",              None,           15000),
        ("X-ray",                     None,           8000),
        ("ECG",                       None,           5000),
        ("ultrasound scan",           None,           8000),
        ("antenatal visit",           None,           3000),
        ("immunization",              None,           2000),
        ("admission (per day)",       None,           10000),
        ("tooth extraction",          None,           5000),
        ("tooth filling",             None,           10000),
        ("scaling and polishing",     None,           10000),
        ("eye test",                  None,           3000),
        ("glasses prescription",      None,           2000),
    ],
    "school": [
        ("tuition",              "nursery/creche",   25000),
        ("tuition",              "primary (1-3)",    30000),
        ("tuition",              "primary (4-6)",    35000),
        ("tuition",              "JSS",              45000),
        ("tuition",              "SSS",              55000),
        ("development levy",     None,                5000),
        ("PTA levy",             None,                3000),
        ("exam fee",             None,                5000),
        ("books / supplies",     None,               10000),
        ("uniform",              None,                8000),
        ("feeding",              "monthly",          20000),
        ("school bus",           "per term",         15000),
        ("after-school care",    None,                5000),
        ("registration fee",     None,               10000),
        ("lesson / extra class", None,                3000),
    ],
}

# Keys that have a SERVICE_PRICE_CATALOG entry
SERVICE_CATALOG_KEYS = set(SERVICE_PRICE_CATALOG.keys())


def service_price_catalog_for_user(user):
    """Return list of (name, unit, price) tuples for the user's service type."""
    key = template_key_for_user(user)
    catalog = SERVICE_PRICE_CATALOG.get(key)
    if catalog is not None:
        return catalog
    btype = getattr(user, "business_type", None)
    return SERVICE_PRICE_CATALOG.get(btype, [])


def has_service_price_catalog(user):
    key = template_key_for_user(user)
    if key in SERVICE_CATALOG_KEYS:
        return True
    btype = getattr(user, "business_type", None)
    return btype in SERVICE_CATALOG_KEYS


_SERVICE_MENU_TEMPLATE_KEYS = frozenset({
    "laundry", "car_wash", "barber", "tailor", "mechanic",
    "artisan_services", "salon_beauty",
})

_FEE_MENU_TEMPLATE_KEYS = frozenset({
    "transport_logistics",
    "real_estate_rentals", "professional_services",
})

_CLINIC_TEMPLATE_KEYS = frozenset({"clinic"})


def menu_group_for_user(user):
    """Return 'stock', 'service', 'fee', 'clinic', 'school', or 'thrift' for home menu layout."""
    if not user:
        return "stock"
    key = template_key_for_user(user)
    if key == "thrift_contribution":
        return "thrift"
    if key == "school":
        return "school"
    if key in _CLINIC_TEMPLATE_KEYS:
        return "clinic"
    if key in _FEE_MENU_TEMPLATE_KEYS:
        return "fee"
    if key in _SERVICE_MENU_TEMPLATE_KEYS:
        return "service"
    # Artisan types with service catalogs (electrician, plumber, etc.)
    btype = getattr(user, "business_type", None)
    if btype in SERVICE_CATALOG_KEYS:
        return "service"
    return "stock"


def get_product_category_suggestion(template_key, product):
    """Return a category string for a product based on the business template, or None."""
    if not template_key or not product:
        return None
    catalog = INDUSTRY_PRODUCT_CATALOG.get(template_key, [])
    product_lower = product.lower().strip()
    for catalog_name, category in catalog:
        if catalog_name == product_lower or product_lower in catalog_name or catalog_name in product_lower:
            return category
    return None


def build_stock_add_guide(user=None):
    """Return a personalised add-stock guide using industry-specific product examples."""
    key = template_key_for_user(user) if user else None
    catalog = INDUSTRY_PRODUCT_CATALOG.get(key, [])
    units = INDUSTRY_DEFAULT_UNITS.get(key, [])

    if catalog and len(catalog) >= 2:
        p1_name, _ = catalog[0]
        p2_name, _ = catalog[1]
        unit1 = units[0] if units else "pack"
        unit2 = units[1] if len(units) > 1 else "piece"
        price_example = (
            f"add stock {p1_name} cost 1500 sell 2000\n"
            f"add stock {p2_name} cost 800 sell 1000\n\n"
            f"With quantity:\n"
            f"add stock {p1_name} 50 {unit1}s at 1500, selling price 2000\n\n"
            f"Quantity only (keeps existing price):\n"
            f"add stock 10 {unit1}s {p1_name}\n\n"
            f"With supplier:\n"
            f"Supplier supply me 50 {unit2}s {p2_name} at 800 each"
        )
    else:
        price_example = (
            "add stock rice cost 3000 sell 4000\n\n"
            "With quantity:\n"
            "add stock honey 10 liters at 10000, selling price 12000\n\n"
            "Quantity only (keeps existing price):\n"
            "add stock 10 bags rice\n\n"
            "With supplier:\n"
            "Ayo supply me 12 bags rice at 5000"
        )

    return f"Add stock with prices:\n{price_example}"
