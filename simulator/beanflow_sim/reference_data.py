"""Static reference definitions: geography and menu.

Everything here is invented for the fictional BeanFlow Coffee chain. City names
and approximate coordinates are public geography; no real company data is used.
Prices are PHP, VAT-exclusive. Lists are ordered by intended popularity: the
first item in a category is its best seller.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Geography: 4 regions -> 12 areas -> 120 stores (DEV)
# ---------------------------------------------------------------------------
REGIONS: list[tuple[int, str]] = [
    (1, "Metro Manila"),
    (2, "North Luzon"),
    (3, "South Luzon"),
    (4, "Visayas & Mindanao"),
]

# Relative demand level per region (applied to every store in the region).
REGION_TRAFFIC = {1: 1.15, 2: 0.92, 3: 0.97, 4: 0.95}

# Store-type mix per region: (mall, street, office, drive_thru, kiosk)
REGION_TYPE_MIX = {
    1: (0.28, 0.18, 0.30, 0.06, 0.18),
    2: (0.30, 0.35, 0.05, 0.18, 0.12),
    3: (0.30, 0.30, 0.06, 0.22, 0.12),
    4: (0.32, 0.30, 0.12, 0.12, 0.14),
}


@dataclass(frozen=True)
class AreaDef:
    area_id: int
    region_id: int
    name: str
    stores: int                                  # stores at store_scale = 1.0
    cities: tuple[tuple[str, float, float], ...]  # (city, lat, lon)


AREAS: list[AreaDef] = [
    AreaDef(1, 1, "Makati & BGC", 14, (("Makati", 14.5547, 121.0244), ("Taguig", 14.5176, 121.0509))),
    AreaDef(2, 1, "Quezon City", 14, (("Quezon City", 14.6760, 121.0437),)),
    AreaDef(3, 1, "Manila & Pasay", 12, (("Manila", 14.5995, 120.9842), ("Pasay", 14.5378, 121.0014))),
    AreaDef(4, 1, "Ortigas & Pasig", 12, (("Pasig", 14.5764, 121.0851), ("Mandaluyong", 14.5794, 121.0359))),
    AreaDef(5, 2, "Central Luzon", 9, (("Angeles", 15.1450, 120.5887), ("San Fernando", 15.0286, 120.6898),
                                        ("Malolos", 14.8527, 120.8160))),
    AreaDef(6, 2, "Baguio & Ilocos", 7, (("Baguio", 16.4023, 120.5960), ("San Fernando La Union", 16.6159, 120.3166),
                                          ("Laoag", 18.1960, 120.5927))),
    AreaDef(7, 3, "Cavite", 11, (("Bacoor", 14.4624, 120.9645), ("Dasmariñas", 14.3294, 120.9367),
                                 ("Imus", 14.4297, 120.9367))),
    AreaDef(8, 3, "Laguna", 11, (("Santa Rosa", 14.3122, 121.1114), ("Calamba", 14.2117, 121.1653),
                                 ("San Pedro", 14.3595, 121.0473))),
    AreaDef(9, 3, "Batangas & Quezon", 9, (("Batangas City", 13.7565, 121.0583), ("Lipa", 13.9411, 121.1631),
                                            ("Lucena", 13.9373, 121.6170))),
    AreaDef(10, 4, "Cebu", 10, (("Cebu City", 10.3157, 123.8854), ("Mandaue", 10.3236, 123.9223),
                                ("Lapu-Lapu", 10.3103, 123.9494))),
    AreaDef(11, 4, "Western Visayas", 6, (("Iloilo City", 10.7202, 122.5621), ("Bacolod", 10.6765, 122.9509))),
    AreaDef(12, 4, "Davao", 5, (("Davao City", 7.1907, 125.4553),)),
]

STORE_NAME_SUFFIX = {
    "mall": "Mall", "street": "Avenue", "office": "Tower", "drive_thru": "Drive-Thru", "kiosk": "Kiosk",
}

# ---------------------------------------------------------------------------
# Menu: 10 categories, 87 SKUs
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CategoryDef:
    category_id: int
    key: str          # stable internal key used by behaviour tables
    name: str
    group: str        # beverage | food | merchandise
    sku_prefix: str
    cost_ratio: float  # unit_cost / price at launch


CATEGORIES: list[CategoryDef] = [
    CategoryDef(1, "espresso", "Espresso Classics", "beverage", "ESP", 0.28),
    CategoryDef(2, "iced_coffee", "Iced Coffee", "beverage", "ICE", 0.27),
    CategoryDef(3, "signature", "Signature Lattes", "beverage", "SIG", 0.30),
    CategoryDef(4, "frappe", "Frappes", "beverage", "FRP", 0.32),
    CategoryDef(5, "non_coffee", "Non-Coffee", "beverage", "NCF", 0.30),
    CategoryDef(6, "tea", "Tea & Refreshers", "beverage", "TEA", 0.22),
    CategoryDef(7, "pastry", "Pastries", "food", "PST", 0.42),
    CategoryDef(8, "sandwich", "Sandwiches & Wraps", "food", "SND", 0.45),
    CategoryDef(9, "meal", "All-Day Meals", "food", "MEL", 0.48),
    CategoryDef(10, "merch", "Merchandise", "merchandise", "MRC", 0.50),
]
CATEGORY_KEYS = [c.key for c in CATEGORIES]
CATEGORY_BY_KEY = {c.key: c for c in CATEGORIES}

# (category_key, item name, {size: price}) ; size None = unsized item.
# launch_offset_days: None = launched long before the history window;
# an int = launched N days after the seed start date (new-product launch).
MENU: list[tuple[str, str, dict[str | None, int], int | None]] = [
    ("espresso", "Americano", {"small": 95, "medium": 115, "large": 135}, None),
    ("espresso", "Cafe Latte", {"small": 125, "medium": 145, "large": 165}, None),
    ("espresso", "Cappuccino", {"small": 125, "medium": 145, "large": 165}, None),
    ("espresso", "Flat White", {"small": 135, "medium": 155, "large": 175}, None),
    ("espresso", "Mocha", {"small": 135, "medium": 155, "large": 175}, None),
    ("iced_coffee", "Iced Spanish Latte", {"small": 135, "medium": 155, "large": 175}, None),
    ("iced_coffee", "Iced Latte", {"small": 125, "medium": 145, "large": 165}, None),
    ("iced_coffee", "Iced Americano", {"small": 100, "medium": 120, "large": 140}, None),
    ("iced_coffee", "Iced Caramel Macchiato", {"small": 145, "medium": 165, "large": 185}, None),
    ("iced_coffee", "Cold Brew", {"small": 130, "medium": 150, "large": 170}, None),
    ("signature", "Sea Salt Latte", {"medium": 165, "large": 185}, None),
    ("signature", "Ube Latte", {"medium": 165, "large": 185}, 40),   # new launch mid-window
    ("signature", "Hazelnut Latte", {"medium": 160, "large": 180}, None),
    ("signature", "Dark Mocha", {"medium": 170, "large": 190}, None),
    ("frappe", "Java Chip Frappe", {"medium": 175, "large": 195}, None),
    ("frappe", "Caramel Frappe", {"medium": 170, "large": 190}, None),
    ("frappe", "Cookies & Cream Frappe", {"medium": 175, "large": 195}, None),
    ("frappe", "Strawberry Cream Frappe", {"medium": 170, "large": 190}, None),
    ("non_coffee", "Matcha Latte", {"medium": 160, "large": 180}, None),
    ("non_coffee", "Iced Matcha", {"medium": 160, "large": 180}, None),
    ("non_coffee", "Iced Chocolate", {"medium": 140, "large": 160}, None),
    ("non_coffee", "Hot Chocolate", {"medium": 135, "large": 155}, None),
    ("non_coffee", "Strawberry Milk", {"medium": 150, "large": 170}, None),
    ("tea", "Calamansi Honey Iced Tea", {"medium": 110, "large": 130}, None),
    ("tea", "Peach Iced Tea", {"medium": 110, "large": 130}, None),
    ("tea", "Mango Refresher", {"medium": 125, "large": 145}, None),
    ("tea", "Lemon Black Tea", {"medium": 100, "large": 120}, None),
    ("pastry", "Butter Croissant", {None: 95}, None),
    ("pastry", "Ensaymada", {None: 75}, None),
    ("pastry", "Banana Bread", {None: 85}, None),
    ("pastry", "Chocolate Chip Cookie", {None: 65}, None),
    ("pastry", "Cinnamon Roll", {None: 105}, None),
    ("pastry", "Blueberry Muffin", {None: 90}, None),
    ("pastry", "Pain au Chocolat", {None: 110}, None),
    ("pastry", "Cheese Roll", {None: 60}, None),
    ("sandwich", "Ham & Cheese Croissant", {None: 175}, None),
    ("sandwich", "Chicken Pesto Sandwich", {None: 195}, None),
    ("sandwich", "Egg & Cheese Muffin", {None: 145}, None),
    ("sandwich", "Tuna Melt", {None: 185}, None),
    ("sandwich", "Beef Tapa Wrap", {None: 199}, None),
    ("sandwich", "Grilled Cheese", {None: 155}, None),
    ("meal", "Chicken Adobo Rice Bowl", {None: 225}, None),
    ("meal", "Beef Tapa Rice", {None: 245}, None),
    ("meal", "Spam & Egg Rice", {None: 210}, None),
    ("meal", "Longganisa Plate", {None: 215}, None),
    ("meal", "Creamy Carbonara", {None: 235}, None),
    ("merch", "Drip Bag Box (10 pcs)", {None: 350}, None),
    ("merch", "House Blend Beans 250g", {None: 450}, None),
    ("merch", "Insulated Tumbler", {None: 650}, 60),                  # new launch mid-window
    ("merch", "Canvas Tote", {None: 299}, None),
]

# Zipf exponent for within-category popularity (rank 1 = best seller).
POPULARITY_EXPONENT = 1.15

# Sizes are encoded in the SKU suffix.
SIZE_SKU_SUFFIX = {"small": "S", "medium": "M", "large": "L"}
