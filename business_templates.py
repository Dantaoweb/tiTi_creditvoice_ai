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
}


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
    lines = ["What category best describes your business?\n"]
    for index, category in enumerate(BUSINESS_CATEGORIES, start=1):
        lines.append(f"{index}. {category['label']}")
    lines.append("\nReply with the number.")
    return "\n".join(lines)


def build_business_type_menu(category):
    lines = [f"{category['label']}\n"]
    for index, (_, label) in enumerate(category["businesses"], start=1):
        lines.append(f"{index}. {label}")
    lines.append("\nReply with the number.")
    return "\n".join(lines)


def template_examples_for_user(user):
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


def business_type_display(user):
    label = getattr(user, "business_type_label", None)
    if label:
        return label
    category = business_category_by_key(getattr(user, "business_category", None))
    return category["label"] if category else "General Business"
