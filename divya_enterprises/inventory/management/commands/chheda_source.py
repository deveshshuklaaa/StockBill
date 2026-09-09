"""Authoritative Chheda catalogue source: 109 rows as provided by Divya Enterprises.

Rows 1-41  -> Chheda Specialities Foods Pvt. Ltd.
Rows 42-109 -> Chheda Agro Food Park Private Ltd.

Fields: serial, name (verbatim), net_weight_kg (Gms, decimal kg),
units_per_master_box (M.Box), mrp, manufacturer, page.
This file is the single source of truth for the importer; do not hand-edit
values — regenerate from the supplier catalogue document instead.
"""

import json
import os

SPECIALITIES = "Chheda Specialities Foods Pvt. Ltd."
AGRO_PARK = "Chheda Agro Food Park Private Ltd."

# (serial, name, gms, mbox, mrp, page)
_ROWS = [
    (1, "Chheda's Yellow banana Chips", "0.014", 240, "5.00", 1),
    (2, "Chheda's Lightly Salted Potato Chips - (B)", "0.015", 192, "5.00", 1),
    (3, "Chheda's Lightly Salted Potato Chips - (Y)", "0.015", 192, "5.00", 1),
    (4, "Chheda's Chilli Flaminn\u2019 Potato Chips", "0.020", 180, "5.00", 1),
    (5, "Chheda's Potato Chips Sizzlin Peri Peri", "0.015", 192, "5.00", 1),
    (6, "Chheda's Mexican Tomato Potato Chips", "0.020", 180, "5.00", 1),
    (7, "Chheda's Chipsona Potato Chips Sour Cream n Onion", "0.014", 180, "5.00", 1),
    (8, "Chheda's Chipsona Potato Chips Mast Masala", "0.014", 180, "5.00", 1),
    (9, "Chheda's Farali Potato Chivda", "0.019", 120, "5.00", 1),
    (10, "Chheda's Tikha Farali Chivda", "0.019", 120, "5.00", 1),
    (11, "Chheda's Peanut Bar", "0.018", 360, "5.00", 1),
    (12, "Chheda's 3 in 1 Chikki", "0.018", 360, "5.00", 1),
    (13, "Chheda's Rusk", "0.036", 250, "5.00", 1),
    (14, "Chheda's Papdi Gathiya", "0.022", 240, "5.00", 1),
    (15, "Chheda's Yellow Banana Chips", "0.025", 192, "10.00", 1),
    (16, "Chheda's Coconut Yellow Banana Chips", "0.026", 192, "10.00", 1),
    (17, "Chheda's Potato Chips Lightly Salted", "0.028", 144, "10.00", 1),
    (18, "Chheda's Chilli Flaminn\u2019 Potato Chips", "0.035", 108, "10.00", 1),
    (19, "Chheda's Potato Chips Sizzlin Peri Peri", "0.030", 144, "10.00", 1),
    (20, "Chheda's Khatta Mitha Tomato Potato Chips", "0.028", 108, "10.00", 1),
    (21, "Chheda's Chipsona Potato Chips Sour Cream n Onion", "0.028", 108, "10.00", 1),
    (22, "Chheda's Chipsona Potato Chips Classic Salted", "0.028", 90, "10.00", 1),
    (23, "Chheda's Choco Vanilla Snax", "0.025", 192, "10.00", 1),
    (24, "Chheda's Farali Potato Chivda", "0.032", 180, "10.00", 1),
    (25, "Udupi Munch Sabudana Chivda", "0.042", 180, "10.00", 1),
    (26, "Chheda's Light N Crispy Poha Chivda", "0.042", 228, "10.00", 1),
    (27, "Chheda's Bombay Mix", "0.055", 180, "10.00", 1),
    (28, "Chheda's Peanut Chikki Bar", "0.035", 240, "10.00", 1),
    (29, "Chheda's Rajgeera Bar", "0.035", 288, "10.00", 1),
    (30, "Minilo Vanilla Mawa Cake", "0.025", 300, "10.00", 1),
    (31, "Chheda's Yellow Banana Chips", "0.030", 120, "20.00", 1),
    (32, "Chheda's Lightly Salted Potato Chips", "0.045", 60, "20.00", 1),
    (33, "Chheda's Chilli Flaminn\u2019 Potato Chips", "0.045", 60, "20.00", 1),
    (34, "Chheda's Mexican Tomato Potato Chips", "0.045", 60, "20.00", 1),
    (35, "Chheda's Chipsona Potato Chips Classic Salted", "0.040", 60, "20.00", 1),
    (36, "Chheda's Chipsona Potato Chips Sour Cream n Onion", "0.040", 60, "20.00", 1),
    (37, "Chheda's Chipsona Potato Chips Mast Masala", "0.040", 60, "20.00", 1),
    (38, "Chheda's Chipsona Potato Chips Peri Peri", "0.040", 60, "20.00", 1),
    (39, "Chheda's Light N Crispy Poha Chivda", "0.062", 228, "20.00", 1),
    (40, "Chheda's Farali Potato Chivda", "0.040", 180, "20.00", 1),
    (41, "Chheda's Choco Vanilla Snax", "0.042", 144, "20.00", 1),
    (42, "Udupi Munch Sabudana Chivda", "0.021", 360, "5.00", 1),
    (43, "Chheda's Bombay Mix", "0.027", 480, "5.00", 1),
    (44, "Udupi Munch Masala Sabudana Chivda", "0.021", 360, "5.00", 1),
    (45, "Chheda's Salt-n-Pepper Banana Chips", "0.015", 216, "5.00", 1),
    (46, "Chheda's Cheese Balls", "0.020", 120, "5.00", 2),
    (47, "Chheda's Tomato Balls", "0.028", 120, "5.00", 2),
    (48, "Chheda's Tomato Wheels", "0.028", 120, "5.00", 2),
    (49, "Chheda's Masala Wheels", "0.024", 120, "5.00", 2),
    (50, "Chheda's Chana Dal", "0.019", 600, "5.00", 2),
    (51, "Chheda's Tasty Nuts", "0.017", 600, "5.00", 2),
    (52, "Chheda's Masala Moon Cups", "0.018", 120, "5.00", 2),
    (53, "Chheda's Moong Dal", "0.018", 600, "5.00", 2),
    (54, "Chheda's Pasta Masala", "0.020", 120, "5.00", 2),
    (55, "Chheda's Krispy Korn Masala", "0.029", 120, "5.00", 2),
    (56, "Chheda's Krispy Korn Peri Peri", "0.024", 120, "5.00", 2),
    (57, "Chheda's Bhel Mix", "0.021", 288, "5.00", 2),
    (58, "Chheda's Masala Sev Murmura", "0.023", 216, "5.00", 2),
    (59, "Chheda's Finger Pops Salted", "0.021", 120, "5.00", 2),
    (60, "Chheda's Finger Pops Masala", "0.018", 120, "5.00", 2),
    (61, "Chheda's Soya Snax", "0.018", 288, "5.00", 2),
    (62, "Chheda's Bhavnagri Gathiya", "0.020", 480, "5.00", 2),
    (63, "Chheda's Manglori Mix", "0.020", 480, "5.00", 2),
    (64, "Chheda's Sev Murmura", "0.026", 288, "5.00", 2),
    (65, "Chheda's Chinese Noodles", "0.022", 144, "5.00", 2),
    (66, "Chheda's Jeera Papad", "0.018", 120, "5.00", 2),
    (67, "Chheda's Masala Papad", "0.018", 120, "5.00", 2),
    (68, "Chheda's Aloo Bhujia", "0.022", 600, "5.00", 2),
    (69, "Chheda's Soya Snax", "0.038", 144, "10.00", 2),
    (70, "Chheda's Salt-n-Pepper Banana Chips", "0.030", 144, "10.00", 2),
    (71, "Chheda's Tomato Banana Chips", "0.030", 144, "10.00", 2),
    (72, "Chheda's Masala Banana Chips", "0.030", 144, "10.00", 2),
    (73, "Chheda's Krispy Korn Masala", "0.050", 120, "10.00", 2),
    (74, "Chheda's Krispy Korn Peri Peri", "0.048", 144, "10.00", 2),
    (75, "Chheda's Finger Pops Salted", "0.038", 80, "10.00", 2),
    (76, "Chheda's Finger Pops Masala", "0.038", 80, "10.00", 2),
    (77, "Chheda's Pasta Masala", "0.038", 80, "10.00", 2),
    (78, "Chheda's Potato Corn Stix", "0.030", 120, "10.00", 2),
    (79, "Chheda's Salted French Fries", "0.027", 80, "10.00", 2),
    (80, "Chheda's Masala French Fries", "0.027", 80, "10.00", 2),
    (81, "Chheda's Masala Moon Cups", "0.038", 80, "10.00", 2),
    (82, "Chheda's Bhel Mix", "0.044", 180, "10.00", 2),
    (83, "Chheda's Alu Bhujia", "0.035", 288, "10.00", 2),
    (84, "Chheda's Small Bhakarwadi", "0.038", 192, "10.00", 2),
    (85, "Chheda's Tikhat Sev", "0.038", 192, "10.00", 2),
    (86, "Chheda's Salted Peanuts", "0.032", 192, "10.00", 2),
    (87, "Chheda's Roasted Chana", "0.042", 192, "10.00", 2),
    (88, "Chheda's Tasty Nuts", "0.035", 192, "10.00", 2),
    (89, "Chheda's Moong Dal", "0.034", 336, "10.00", 2),
    (90, "Udupi Munch Madras Mix", "0.040", 192, "10.00", 2),
    (91, "Udupi Munch Masala Murukku", "0.040", 192, "10.00", 2),
    (92, "Chheda's Chana Chor", "0.035", 192, "10.00", 2),
    (93, "Chheda's Tikha Gathiya", "0.048", 180, "10.00", 2),
    (94, "Chheda's Finger Pops Salted", "0.040", 60, "20.00", 2),
    (95, "Chheda's Finger Pops Masala", "0.040", 60, "20.00", 2),
    (96, "Chheda's Salted French Fries", "0.052", 60, "20.00", 3),
    (97, "Chheda's Masala French Fries", "0.052", 60, "20.00", 3),
    (98, "Chheda's Masala Moon Cups", "0.042", 60, "20.00", 3),
    (99, "Chheda's Pasta Masala", "0.042", 60, "20.00", 3),
    (100, "Chheda's Small Bhakarwadi", "0.035", 200, "20.00", 3),
    (101, "Chheda's Aloo Bhujia", "0.042", 288, "20.00", 3),
    (102, "Chheda's Tasty Nuts", "0.052", 192, "20.00", 3),
    (103, "Chheda's Moong Dal", "0.044", 192, "20.00", 3),
    (104, "Chheda's Bhel Mix", "0.062", 180, "20.00", 3),
    (105, "Chheda's Tikhat Sev", "0.052", 192, "20.00", 3),
    (106, "Soya Snax", "0.043", 144, "20.00", 3),
    (107, "Chheda's Krispy Korn Masala", "0.062", 108, "20.00", 3),
    (108, "Chheda's Krispy Korn Peri Peri", "0.052", 144, "20.00", 3),
    (109, "Potato Corn Stix Cream-n-Onion 52g", "0.052", 100, "20.00", 3),
]

assert len(_ROWS) == 109, len(_ROWS)
assert [r[0] for r in _ROWS] == list(range(1, 110)), "serials must be exactly 1..109"


def build_rows():
    rows = []
    for serial, name, gms, mbox, mrp, page in _ROWS:
        manufacturer = SPECIALITIES if serial <= 41 else AGRO_PARK
        rows.append(
            {
                "serial": serial,
                "name": name,
                "net_weight_kg": gms,
                "units_per_master_box": mbox,
                "mrp": mrp,
                "manufacturer": manufacturer,
                "page": page,
            }
        )
    return rows


if __name__ == "__main__":
    # Regenerate chheda_catalogue.json next to this script.
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "chheda_catalogue.json"
    )
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_rows(), f, indent=1, ensure_ascii=False)
    print(f"wrote {len(build_rows())} rows to {path}")
