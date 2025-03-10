"""Parse PSA file into object"""

from __future__ import annotations
from abc import ABC
import csv
from dataclasses import asdict, dataclass, fields
import enum
import typing as t
from uuid import uuid4

UNIT_CONVERTER = 10


class PSAItem(ABC):
    """Base class for PSA line wrappers"""

    @classmethod
    def get_headers(cls) -> t.Tuple[str, ...]:
        """Get the headers for this item"""
        return tuple(field.name for field in fields(cls))

    @staticmethod
    def generate_guid() -> str:
        """Generate a unique GUID"""
        return str(uuid4()).upper()

    def to_array(self) -> t.List[str]:
        """Convert to a list of strings for CSV output"""
        d = asdict(self)
        values = []
        for i in self.get_headers():
            value = d[i]
            values.append(value_to_csv(value))
        return values

    def to_dict(self) -> t.Dict[str, str]:
        """Convert to a dict for a dataframe"""
        d = asdict(self)
        result: t.Dict[str, str] = {}
        for key in self.get_headers():
            result[key] = value_to_csv(d[key])
        return result

    def to_csv(self) -> str:
        """Convert to a CSV line"""
        return ",".join(self.to_array())

    @classmethod
    def from_array(cls, fields: t.Sequence[t.Any]):
        """Create a PSAItem from a list of CSV fields"""
        headers = cls.get_headers()

        result = cls()
        for key, field in zip(headers, fields):
            try:
                result.set(key, field)
            except Exception as e:
                print(f"ignore error {e}")

        return result

    def _sanitize(self, key: str, value: t.Any) -> t.Any:
        default_value = getattr(self, key)
        try:
            if isinstance(default_value, float):
                return float(value)
            if isinstance(default_value, int):
                return int(value)
        except ValueError:
            return 0

        if value is None:
            return ""

        return str(value)

    def set(self, key: str, value: t.Any) -> None:
        """Set a value by key"""
        if key not in self.get_headers():
            raise PSAItemError(f"Invalid key {key} for {self.__class__.__name__}")

        sane_value = self._sanitize(key, value)
        setattr(self, key, sane_value)


class PsaParser:
    def __init__(self, psa_content: str) -> None:
        self.psa_content = psa_content
        self.orientations = [
            "front",
            "Front 90",
            "Side",
            "Side 90",
            "top",
            "Top 90",
            "Back",
            "Back 90",
            "Right",
            "Right 90",
            "Base",
            "Base 90",
            "Front 180",
            "Front 270",
            "Side 180",
            "Side 270",
            "Top 180",
            "Top 270",
            "Back 180",
            "Back 270",
            "Right 180",
            "Right 270",
            "Base 180",
            "Base 270",
        ]
        self.products: t.List[PSAProduct] = []
        self.segments: t.List[t.Dict[str, t.Any]] = []
        self.fixtures: t.List[t.Dict[str, t.Any]] = []
        self.position_items: t.List[t.Tuple[PSAPosition, t.Dict[str, t.Any]]] = []
        self.fixtures_index: t.Dict[str, t.Any] = {}
        self.bays: t.List[t.Dict[str, t.Any]] = []
        self.bay_height = 0
        self.psa_planogram = PSAPlanogram()

        segment_id = 0
        fixture_id = 0

        notch_spacing = 0.0
        notch_offset = 0.0
        notch_width = 0.0

        lines = (
            row
            for row in csv.reader(
                (
                    line.replace("\\r\\n", "<newline>")
                    for line in psa_content.splitlines()
                ),
                delimiter=",",
                escapechar="\\",
                quoting=csv.QUOTE_NONE,
                lineterminator="\r\n",
            )
            if len(row) > 1
        )
        for items in lines:
            if items[0] == "Planogram":
                self.psa_planogram = PSAPlanogram.from_array(items)
                notch_offset = self.psa_planogram.notch_offset * UNIT_CONVERTER
                notch_spacing = self.psa_planogram.notch_spacing * UNIT_CONVERTER
                if notch_spacing <= 0:
                    notch_spacing = 1

                notch_width = self.psa_planogram.notch_width * UNIT_CONVERTER

            elif items[0] == "Product":
                psa_product = PSAProduct.from_array(items)
                self.products.append(psa_product)

            elif items[0] == "Segment":
                segment_id += 1
                self.fixtures_index[str(segment_id)] = 0
                psa_segment = PSASegment.from_array(items)
                bay_height = psa_segment.height * UNIT_CONVERTER
                bay_width = psa_segment.width * UNIT_CONVERTER + notch_width
                bay_depth = psa_segment.depth * UNIT_CONVERTER
                bay_x = psa_segment.x * UNIT_CONVERTER
                if segment_id > 1 and bay_x == 0:
                    bay_x = self.bays[-1]["bay_x"] + self.bays[-1]["bay_width"]

                segment = {
                    "bay_no": segment_id,
                    "bay_width": bay_width,
                    "bay_height": bay_height,
                    "bay_depth": bay_depth,
                    "bay_x": bay_x,
                    "shelf_step": notch_spacing,
                    "first_notch_y": notch_offset,
                    "shelves": [],
                }
                self.segments.append(segment)
                self.bays.append(
                    {
                        "bay_no": segment_id,
                        "bay_height": bay_height,
                        "bay_width": bay_width,
                        "bay_depth": bay_depth,
                        "first_notch_y": notch_offset,
                        "bay_x": bay_x,
                        "shelf_step": notch_spacing,
                        "shelves": [],
                    }
                )

            elif items[0] == "Fixture":
                psa_fixture = PSAFixture.from_array(items)
                shelf_x = psa_fixture.x * UNIT_CONVERTER
                shelf_y = psa_fixture.y * UNIT_CONVERTER
                segment_index = self.get_segment_index(shelf_x)
                # segment_index += 1
                fixture_id += 1
                # Cannot use notch_no = (y_bottom - planogram_base_height * UNIT_CONVERTER) / planogram_notch_spacing * 10 + 1
                notch_no = self.get_notch_no(psa_fixture)

                fixture = {
                    "segment_index": segment_index,
                    "shelf_no": fixture_id,
                    "shelf_name": psa_fixture.name,
                    "shelf_colour": psa_fixture.color,
                    "shelf_type": psa_fixture.shelf_type.name,
                    "shelf_width": psa_fixture.width * UNIT_CONVERTER,
                    "shelf_thickness": psa_fixture.height * UNIT_CONVERTER,
                    "shelf_depth": psa_fixture.depth * UNIT_CONVERTER,
                    "can_combine": psa_fixture.can_combine,
                    "notch_no": int(notch_no),
                    "notch_num": int(notch_no),
                    "shelf_slope": psa_fixture.slope * UNIT_CONVERTER,
                    "shelf_x": shelf_x,
                    "shelf_y": shelf_y,
                    "assembly": psa_fixture.assembly,
                    "items": [],
                }
                self.fixtures.append(fixture)

            elif items[0] == "Position":
                psa_position = PSAPosition.from_array(items)
                self.position_items.append((psa_position, self.fixtures[-1]))

        self.fixtures.sort(key=lambda e: (e["shelf_x"], -e["shelf_y"]))

    def get_product(self, item_id: str) -> PSAProduct:
        for product in self.products:
            if product.upc == item_id:
                return product

        raise ValueError(f"Product not found {item_id}")

    def get_segment_index(self, psa_fixture_x: float) -> int:
        back_ordered_bays = [*enumerate(sorted(self.bays, key=lambda b: b["bay_x"]))][
            ::-1
        ]
        for index, bay in back_ordered_bays:
            if bay["bay_x"] <= psa_fixture_x:
                return index + 1

        return 1

    def get_notch_no(self, psa_fixture: PSAFixture) -> int:
        if psa_fixture.shelf_type == PSAFixtureType.OBSTRUCTION:
            if not self.fixtures:
                return 0
            return self.fixtures[-1]["notch_no"]

        shelf_y = psa_fixture.y * UNIT_CONVERTER
        shelf_height = psa_fixture.height * UNIT_CONVERTER
        notch_offset = self.psa_planogram.notch_offset * UNIT_CONVERTER
        notch_spacing = self.psa_planogram.notch_spacing * UNIT_CONVERTER

        notch_no = int((shelf_y + shelf_height - notch_offset) / notch_spacing) + 1
        return max(notch_no, 0)

    def decode_psa(self, product_master={}) -> t.Dict:
        for psa_position, fixture_data in self.position_items:
            product = self.get_product(psa_position.upc)
            prod_x = float(psa_position.x) * UNIT_CONVERTER
            prod_y = float(psa_position.y) * UNIT_CONVERTER
            bay_no = get_segment_index(prod_x, self.segments) + 1
            if bay_no == 0:
                raise ValueError(f"Invalid Position[x:{prod_x} y:{prod_y}] with Bay")
            fixture_index = get_item_fixture_index(bay_no, prod_y, self.fixtures)
            if fixture_index == -1:
                raise ValueError(f"Invalid Position[x:{prod_x} y:{prod_y}] with Shelf")

            num_rows = int(psa_position.vfacings)
            h_facings = int(psa_position.hfacings)
            facings = int(num_rows * h_facings)

            item_id = str(product.upc)
            position = {
                "item_id": item_id,
                "cdt0": product_master.get(item_id, {}).get("variant", None),
                "cdt1": product_master.get(item_id, {}).get("cdt1", None),
                "cdt2": product_master.get(item_id, {}).get("cdt2", None),
                "cdt3": product_master.get(item_id, {}).get("cdt3", None),
                "width": int(float(product.width) * UNIT_CONVERTER),
                "height": int(float(product.height) * UNIT_CONVERTER),
                "depth": int(float(product.depth) * UNIT_CONVERTER),
                "facings": facings,
                "orientation": self.orientations[int(psa_position.orientation)],
                "nesting_width ": 0,
                "rotated": False,
                "num_rows": num_rows,
                "prod_x": prod_x,
                "prod_y": prod_y,
                "tray_width": product.tray_width * UNIT_CONVERTER,
                "tray_height": product.tray_height * UNIT_CONVERTER,
                "tray_depth": product.tray_depth * UNIT_CONVERTER,
                "unit_width": float(product.width) * UNIT_CONVERTER,
                "unit_height": float(product.height) * UNIT_CONVERTER,
                "unit_depth": float(product.depth) * UNIT_CONVERTER,
                "case_width": product.case_width * UNIT_CONVERTER,
                "case_height": product.case_height * UNIT_CONVERTER,
                "case_depth": product.case_depth * UNIT_CONVERTER,
                "price": product.price,
                "display_width": product.display_width,
                "display_height": product.display_height,
                "display_depth": product.display_depth,
                "case_number_wide": product.case_number_wide,
                "case_number_high": product.case_number_high,
                "case_number_deep": product.case_number_deep,
                "tray_number_wide": product.tray_number_wide,
                "tray_number_high": product.tray_number_high,
                "tray_number_deep": product.tray_number_deep,
                "id": product.id,
                "name": product.name,
                "brand": product.brand,
                "category": product.category,
                "subcategory": product.subcategory,
                "size": product.size,
                "upc": product.upc,
                "uom": product.uom,
                "supplier": product.supplier,
                "weight": product.weight,
                "inner_pack": product.inner_pack,
                "colour": product.color,
            }  # satisfied PogItem(BaseModel)
            fixture_data["items"].append(position)

        combine_map: t.Dict[int, t.Dict[str, t.Any]] = {}
        for fixture in self.fixtures:
            fixture["items"].sort(key=lambda e: e["prod_x"])
            segment_index = next(
                (
                    i
                    for i, seg in enumerate(self.segments)
                    if seg["bay_no"] == fixture["segment_index"]
                ),
                -1,
            )
            bay_no = str(self.segments[segment_index]["bay_no"])
            self.fixtures_index[bay_no] += 1
            shelf_no = self.fixtures_index[bay_no]
            shelf_y = float(fixture["shelf_y"])
            shelf_x = float(fixture["shelf_x"])
            segment_width = float(self.segments[segment_index]["bay_width"])
            can_combine = fixture["can_combine"]
            if can_combine > 0:
                if (
                    shelf_no in combine_map
                    and combine_map[shelf_no]["shelf_y"] == shelf_y
                ):
                    combine_map[shelf_no]["bays"].append(segment_index + 1)
                    combine_map[shelf_no]["items"].extend(fixture["items"])
                else:
                    details = {
                        "bays": [segment_index + 1],
                        "shelf_y": shelf_y,
                        "items": fixture["items"][::],
                    }
                    combine_map[shelf_no] = details

            self.bays[segment_index]["shelves"].append(
                {
                    "notch_no": fixture["notch_no"],
                    "notch_num": fixture["notch_num"],
                    "segment_width": segment_width,
                    "shelf_slope": fixture["shelf_slope"],
                    "shelf_no": shelf_no,
                    "shelf_type": fixture["shelf_type"],
                    "shelf_name": fixture["shelf_name"],
                    "shelf_colour": fixture["shelf_colour"],
                    "shelf_height": find_highest_item(fixture["items"])
                    + fixture["shelf_thickness"],
                    "shelf_thickness": fixture["shelf_thickness"],
                    "shelf_width": float(fixture["shelf_width"]),
                    "shelf_depth": float(fixture["shelf_depth"]),
                    "can_combine": can_combine,
                    "assembly": fixture["assembly"],
                    "shelf_y": shelf_y,
                    "shelf_x": shelf_x,
                    "finger_space": 0,
                    "items": fixture["items"],
                }
            )

        for item in combine_map:
            bay_list = combine_map[item]["bays"]
            if len(bay_list) <= 1:
                continue
            items = combine_map[item]["items"]
            shelf_index = item - 1
            for index, bay_no in enumerate(bay_list):
                if len(self.bays[index]["shelves"]) < item:
                    continue

                bay = next(bay for bay in self.bays if bay["bay_no"] == bay_no)

                if index == 0:
                    bay_width = bay["bay_width"]
                    bay["shelves"][shelf_index]["segment_width"] = bay_width * len(
                        bay_list
                    )
                    bay["shelves"][shelf_index]["items"] = items
                    bay["shelves"][shelf_index]["shelf_height"] = (
                        find_highest_item(items)
                        + bay["shelves"][shelf_index]["shelf_thickness"]
                    )
                else:
                    bay["shelves"][shelf_index]["segment_width"] = 0
                    bay["shelves"][shelf_index]["items"] = []

        for bay in self.bays:
            bay["base_height"] = self.psa_planogram.base_height * UNIT_CONVERTER
            bay["bay_depth"] = self.psa_planogram.depth * UNIT_CONVERTER
        return {"bays": self.bays}


@dataclass
class PSAProduct(PSAItem):
    product: str = "Product"
    upc: str = ""
    id: str = ""
    name: str = "Product"
    key: int = 0
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0
    color: str = "8421504"
    abbrev_name: str = ""
    size: str = ""
    uom: str = ""
    manufacturer: str = ""
    category: str = ""
    supplier: str = ""
    inner_pack: int = 0
    x_nesting: float = 0.0
    y_nesting: float = 0.0
    z_nesting: float = 0.0
    pegholes: int = 1
    peghole_x: float = 0.0
    peghole_y: float = 0.0
    peghole_width: float = 0.0
    peghole_2_x: float = 0.0
    peghole_2_y: float = 0.0
    peghole_2_width: float = 0.0
    peghole_3_x: float = 0.0
    peghole_3_y: float = 0.0
    peghole_3_width: float = 0.0
    package_style: int = 0
    peg_id: str = ""
    finger_space_y: float = 0.0
    jumble_factor: float = 0.0
    price: float = 0.0
    case_cost: float = 0.0
    tax_code: int = 1
    unit_movement: float = 0.0
    share: int = 0
    case_multiple: int = 0
    days_supply: float = 0.0
    combined_performance_index: int = 0
    peg_span: int = 0
    minimum_units: int = 0
    maximum_units: int = 0
    shape_id: str = ""
    bitmap_id_override: str = ""
    tray_width: float = 0.0
    tray_height: float = 0.0
    tray_depth: float = 0.0
    tray_number_wide: int = 0
    tray_number_high: int = 0
    tray_number_deep: int = 0
    tray_total_number: int = 0
    tray_max_high: float = 0.0
    case_width: float = 0.0
    case_height: float = 0.0
    case_depth: float = 0.0
    case_number_wide: float = 0.0
    case_number_high: float = 0.0
    case_number_deep: float = 0.0
    case_total_number: int = 0
    case_max_high: float = 0.0
    display_width: float = 0.0
    display_height: float = 0.0
    display_depth: float = 0.0
    display_number_wide: float = 0.0
    display_number_high: float = 0.0
    display_number_deep: float = 0.0
    display_total_number: int = 0
    display_max_high: float = 0.0
    alternate_width: float = 0.0
    alternate_height: float = 0.0
    alternate_depth: float = 0.0
    alternate_number_wide: float = 0.0
    alternate_number_high: float = 0.0
    alternate_number_deep: float = 0.0
    alternate_total_number: int = 0
    alternate_max_high: float = 0.0
    loose_width: float = 0.0
    loose_height: float = 0.0
    loose_depth: float = 0.0
    loose_number_wide: float = 0.0
    loose_number_high: float = 0.0
    loose_number_deep: float = 0.0
    loose_total_number: int = 0
    loose_max_high: float = 0.0
    merchxmin: float = -1.0
    merchxmax: float = -1.0
    merchxuprights: int = -1
    merchxcaps: int = -1
    merchxplacement: int = 0
    merchxnumber: int = 0
    merchxsize: int = 0
    merchxdirection: int = -1
    merchxsqueeze: int = -1
    merchymin: float = -1.0
    merchymax: float = -1.0
    merchyuprights: int = -1
    merchycaps: int = -1
    merchyplacement: int = 0
    merchynumber: int = 0
    merchysize: int = 0
    merchydirection: int = -1
    merchysqueeze: int = -1
    merchzmin: float = -1.0
    merchzmax: float = -1.0
    merchzuprights: int = -1
    merchzcaps: int = -1
    merchzplacement: int = 0
    merchznumber: int = 0
    merchzsize: int = 0
    merchzdirection: int = -1
    merchzsqueeze: int = -1
    number_of_positions: int = 1
    desc_1: str = ""
    desc_2: str = ""
    desc_3: str = ""
    desc_4: str = ""
    desc_5: str = ""
    desc_6: str = ""
    desc_7: str = ""
    desc_8: str = ""
    desc_9: str = ""
    desc_10: str = ""
    desc_11: str = ""
    desc_12: str = ""
    desc_13: str = ""
    desc_14: str = ""
    desc_15: str = ""
    desc_16: str = ""
    desc_17: str = ""
    desc_18: str = ""
    desc_19: str = ""
    desc_20: str = ""
    desc_21: str = ""
    desc_22: str = ""
    desc_23: str = ""
    desc_24: str = ""
    desc_25: str = ""
    desc_26: str = ""
    desc_27: str = ""
    desc_28: str = ""
    desc_29: str = ""
    desc_30: str = ""
    desc_31: str = ""
    desc_32: str = ""
    desc_33: str = ""
    desc_34: str = ""
    desc_35: str = ""
    desc_36: str = ""
    desc_37: str = ""
    desc_38: str = ""
    desc_39: str = ""
    desc_40: str = ""
    desc_41: str = ""
    desc_42: str = ""
    desc_43: str = ""
    desc_44: str = ""
    desc_45: str = ""
    desc_46: str = ""
    desc_47: str = ""
    desc_48: str = ""
    desc_49: str = ""
    desc_50: str = ""
    value_1: float = 0.0
    value_2: float = 0.0
    value_3: float = 0.0
    value_4: float = 0.0
    value_5: float = 0.0
    value_6: float = 0.0
    value_7: float = 0.0
    value_8: float = 0.0
    value_9: float = 0.0
    value_10: float = 0.0
    value_11: float = 0.0
    value_12: float = 0.0
    value_13: float = 0.0
    value_14: float = 0.0
    value_15: float = 0.0
    value_16: float = 0.0
    value_17: float = 0.0
    value_18: float = 0.0
    value_19: float = 0.0
    value_20: float = 0.0
    value_21: float = 0.0
    value_22: float = 0.0
    value_23: float = 0.0
    value_24: float = 0.0
    value_25: float = 0.0
    value_26: float = 0.0
    value_27: float = 0.0
    value_28: float = 0.0
    value_29: float = 0.0
    value_30: float = 0.0
    value_31: float = 0.0
    value_32: float = 0.0
    value_33: float = 0.0
    value_34: float = 0.0
    value_35: float = 0.0
    value_36: float = 0.0
    value_37: float = 0.0
    value_38: float = 0.0
    value_39: float = 0.0
    value_40: float = 0.0
    value_41: float = 0.0
    value_42: float = 0.0
    value_43: float = 0.0
    value_44: float = 0.0
    value_45: float = 0.0
    value_46: float = 0.0
    value_47: float = 0.0
    value_48: float = 0.0
    value_49: float = 0.0
    value_50: float = 0.0
    flag_1: int = 0
    flag_2: int = 0
    flag_3: int = 0
    flag_4: int = 0
    flag_5: int = 0
    flag_6: int = 0
    flag_7: int = 0
    flag_8: int = 0
    flag_9: int = 0
    flag_10: int = 0
    minimum_squeeze_factor_x: float = 1.0
    minimum_squeeze_factor_y: float = 1.0
    minimum_squeeze_factor_z: float = 1.0
    maximum_squeeze_factor_x: float = 1.0
    maximum_squeeze_factor_y: float = 1.0
    maximum_squeeze_factor_z: float = 1.0
    fill_pattern: int = 0
    model_filename: str = ""
    brand: str = ""
    subcategory: str = ""
    weight: float = 0.0
    planogram_alias: str = ""
    changed: int = 0
    front_overhang: int = 0
    finger_space_x: int = 0
    dbkey1: int = -1
    dbkey2: int = -1
    dbkey3: int = -1
    dbkey4: int = -1
    dbkey5: int = -1
    dbkey6: int = -1
    dbkey7: int = -1
    dbkey8: int = -1
    dbkey9: int = -1
    dbkey10: int = -1
    status: str = ""
    date_created: int = 0
    date_modified: int = 0
    date_pending: int = 0
    date_effective: int = 0
    date_finished: int = 0
    date_1: int = 0
    date_2: int = 0
    date_3: int = 0
    created_by: str = ""
    modified_by: str = ""
    transparency: int = 0
    peak_safety_factor: float = -0.01
    backroom_stock: float = -0.01
    delivery_schedule: str = ""
    partid: str = ""
    authority_level: int = 0
    bitmap_id_override_unit: int = 0
    model_filename_lookup: int = 0
    default_merch_style: int = -1
    automatic_model: int = 2
    dbguid: str = ""
    source: int = 0
    technicalkey: int = -1
    squeeze_expand_units_only: int = 0
    service_level: int = 0

    @classmethod
    def get_headers(cls) -> t.Tuple[str, ...]:
        return tuple(field.name for field in fields(cls))


@dataclass
class PSAPosition(PSAItem):
    position: str = "Position"
    upc: str = ""
    id: str = ""
    key: str = ""
    x: float = 0.0
    width: float = 0.0
    y: float = 0.0
    height: float = 0.0
    z: float = 0.0
    depth: float = 0.0
    slope: float = 0.0
    angle: float = 0.0
    roll: float = 0.0
    merch_style: int = 0
    hfacings: float = 0.0
    vfacings: float = 0.0
    dfacings: float = 0.0
    x_cap_num: int = 0
    x_cap_nested: int = 0
    x_cap_reversed: int = 0
    x_cap_orientation: int = 8
    y_cap_num: int = 0
    y_cap_nested: int = 0
    y_cap_reversed: int = 0
    y_cap_orientation: int = 4
    z_cap_num: int = 0
    z_cap_nested: int = 0
    z_cap_reversed: int = 0
    z_cap_orientation: int = 0
    orientation: int = 0
    jumble_width: int = 0
    jumble_height: int = 0
    jumble_depth: int = 0
    merch_style_width: float = 0.0
    merch_style_height: float = 0.0
    merch_style_depth: float = 0.0
    full_width: float = 0.0
    full_height: float = 0.0
    full_depth: float = 0.0
    x_sub_units: int = 1
    y_sub_units: int = 1
    z_sub_units: int = 1
    peg_id: str = ""
    manual_units: int = 1
    rank_x: int = 4
    rank_y: int = 1
    rank_z: int = 1
    peg_span: int = 0
    always_float: int = 0
    primary_position_label_format_name: str = ""
    secondary_position_label_format_name: str = ""
    merchxmin: float = 0.0
    merchxmax: float = 0.0
    merchxuprights: float = 0.0
    merchxcaps: float = 0.0
    merchxplacement: float = 0.0
    merchxnumber: int = 0
    merchxsize: float = 0.0
    merchxdirection: int = -1
    merchxsqueeze: int = -1
    merchymin: float = 0.0
    merchymax: float = 0.0
    merchyuprights: float = 0.0
    merchycaps: float = 0.0
    merchyplacement: float = 0.0
    merchynumber: int = 0
    merchysize: float = 0.0
    merchydirection: int = -1
    merchysqueeze: int = -1
    merchzmin: float = 0.0
    merchzmax: float = 0.0
    merchzuprights: float = 0.0
    merchzcaps: float = 0.0
    merchzplacement: float = 0.0
    merchznumber: int = 0
    merchzsize: float = 0.0
    merchzdirection: int = 0
    merchzsqueeze: int = -1
    desc_1: str = ""
    desc_2: str = ""
    desc_3: str = ""
    desc_4: str = ""
    desc_5: str = ""
    desc_6: str = ""
    desc_7: str = ""
    desc_8: str = ""
    desc_9: str = ""
    desc_10: str = ""
    desc_11: str = ""
    desc_12: str = ""
    desc_13: str = ""
    desc_14: str = ""
    desc_15: str = ""
    desc_16: str = ""
    desc_17: str = ""
    desc_18: str = ""
    desc_19: str = ""
    desc_20: str = ""
    desc_21: str = ""
    desc_22: str = ""
    desc_23: str = ""
    desc_24: str = ""
    desc_25: str = ""
    desc_26: str = ""
    desc_27: str = ""
    desc_28: str = ""
    desc_29: str = ""
    desc_30: str = ""
    value_1: float = 0.0
    value_2: float = 0.0
    value_3: float = 0.0
    value_4: float = 0.0
    value_5: float = 0.0
    value_6: float = 0.0
    value_7: float = 0.0
    value_8: float = 0.0
    value_9: float = 0.0
    value_10: float = 0.0
    value_11: float = 0.0
    value_12: float = 0.0
    value_13: float = 0.0
    value_14: float = 0.0
    value_15: float = 0.0
    value_16: float = 0.0
    value_17: float = 0.0
    value_18: float = 0.0
    value_19: float = 0.0
    value_20: float = 0.0
    value_21: float = 0.0
    value_22: float = 0.0
    value_23: float = 0.0
    value_24: float = 0.0
    value_25: float = 0.0
    value_26: float = 0.0
    value_27: float = 0.0
    value_28: float = 0.0
    value_29: float = 0.0
    value_30: float = 0.0
    flag_1: int = 0
    flag_2: int = 0
    flag_3: int = 0
    flag_4: int = 0
    flag_5: int = 0
    flag_6: int = 0
    flag_7: int = 0
    flag_8: int = 0
    flag_9: int = 0
    flag_10: int = 0
    use_target_space_x: int = 0
    use_target_space_y: int = 0
    use_target_space_z: int = 0
    target_space_x: int = 0
    target_space_y: int = 0
    target_space_z: int = 0
    location_id: str = ""
    changed: int = 0
    replenishment_min: int = 0
    replenishment_max: int = 0
    shape_id: str = ""
    bitmap_id_override: str = ""
    hide_if_printing: int = 0
    partid: str = ""
    bitmap_id_override_unit: int = 0
    automatic_model: int = -1
    x_cap_with_units: int = 0
    y_cap_with_units: int = 0
    z_cap_with_units: int = 0


@dataclass
class PSAPlanogram(PSAItem):
    planogram: str = "Planogram"
    name: str = ""
    key: str = ""
    width: float = 0.0
    height: float = 0.0
    depth: float = 0.0
    color: str = ""
    back_depth: float = 1.0
    draw_back: float = 1.0
    base_width: float = 0.0
    base_height: float = 0.0
    base_depth: float = 0.0
    draw_base: int = 1
    base_color: int = 12632256
    draw_notches: int = 1
    notch_offset: float = 0.0
    notch_spacing: float = 0.0
    double_notches: int = 0
    notch_color: int = 0
    notch_marks: int = 1
    draw_pegs: int = 0
    draw_pegholes: int = 0
    traffic_flow: int = 1
    auto_created: int = 0
    shape_id: str = "0"
    bitmap_id: str = "0"
    merchxmin: int = -1
    merchxmax: int = -1
    merchxuprights: int = -1
    merchxcaps: int = -1
    merchxplacement: float = 0
    merchxnumber: int = 0
    merchxsize: int = 0
    merchxdirection: int = -1
    merchxsqueeze: int = -1
    merchymin: int = -1
    merchymax: int = -1
    merchyuprights: int = -1
    merchycaps: int = -1
    merchyplacement: int = 0
    merchynumber: int = 0
    merchysize: int = 0
    merchydirection: int = -1
    merchysqueeze: int = -1
    merchzmin: int = -1
    merchzmax: int = -1
    merchzuprights: int = -1
    merchzcaps: int = -1
    merchzplacement: int = 0
    merchznumber: int = 0
    merchzsize: int = 0
    merchzdirection: int = -1
    merchzsqueeze: int = -1
    combined_performance_index: int = 0
    number_of_stores: int = 1
    notch_width: float = 0.0
    desc_1: str = ""
    desc_2: str = ""
    desc_3: str = ""
    desc_4: str = ""
    desc_5: str = ""
    desc_6: str = ""
    desc_7: str = ""
    desc_8: str = ""
    desc_9: str = ""
    desc_10: str = ""
    desc_11: str = ""
    desc_12: str = ""
    desc_13: str = ""
    desc_14: str = ""
    desc_15: str = ""
    desc_16: str = ""
    desc_17: str = ""
    desc_18: str = ""
    desc_19: str = ""
    desc_20: str = ""
    desc_21: str = ""
    desc_22: str = ""
    desc_23: str = ""
    desc_24: str = ""
    desc_25: str = ""
    desc_26: str = ""
    desc_27: str = ""
    desc_28: str = ""
    desc_29: str = ""
    desc_30: str = ""
    desc_31: str = ""
    desc_32: str = ""
    desc_33: str = ""
    desc_34: str = ""
    desc_35: str = ""
    desc_36: str = ""
    desc_37: str = ""
    desc_38: str = ""
    desc_39: str = ""
    desc_40: str = ""
    desc_41: str = ""
    desc_42: str = ""
    desc_43: str = ""
    desc_44: str = ""
    desc_45: str = ""
    desc_46: str = ""
    desc_47: str = ""
    desc_48: str = ""
    desc_49: str = ""
    desc_50: str = ""
    value_1: float = 0.0
    value_2: float = 0.0
    value_3: float = 0.0
    value_4: float = 0.0
    value_5: float = 0.0
    value_6: float = 0.0
    value_7: float = 0.0
    value_8: float = 0.0
    value_9: float = 0.0
    value_10: float = 0.0
    value_11: float = 0.0
    value_12: float = 0.0
    value_13: float = 0.0
    value_14: float = 0.0
    value_15: float = 0.0
    value_16: float = 0.0
    value_17: float = 0.0
    value_18: float = 0.0
    value_19: float = 0.0
    value_20: float = 0.0
    value_21: float = 0.0
    value_22: float = 0.0
    value_23: float = 0.0
    value_24: float = 0.0
    value_25: float = 0.0
    value_26: float = 0.0
    value_27: float = 0.0
    value_28: float = 0.0
    value_29: float = 0.0
    value_30: float = 0.0
    value_31: float = 0.0
    value_32: float = 0.0
    value_33: float = 0.0
    value_34: float = 0.0
    value_35: float = 0.0
    value_36: float = 0.0
    value_37: float = 0.0
    value_38: float = 0.0
    value_39: float = 0.0
    value_40: float = 0.0
    value_41: float = 0.0
    value_42: float = 0.0
    value_43: float = 0.0
    value_44: float = 0.0
    value_45: float = 0.0
    value_46: float = 0.0
    value_47: float = 0.0
    value_48: float = 0.0
    value_49: float = 0.0
    value_50: float = 0.0
    flag_1: int = 0
    flag_2: int = 0
    flag_3: int = 0
    flag_4: int = 0
    flag_5: int = 0
    flag_6: int = 0
    flag_7: int = 0
    flag_8: int = 0
    flag_9: int = 0
    flag_10: int = 0
    fill_pattern: int = 0
    segments_to_print: str = ""
    file_name: str = ""
    changed: int = 1
    layout_file_name: str = ""
    notes: str = ""
    dbkey1: int = -1
    dbkey2: int = -1
    dbkey3: int = -1
    dbkey4: int = -1
    dbkey5: int = -1
    dbkey6: int = -1
    dbkey7: int = -1
    dbkey8: int = -1
    dbkey9: int = -1
    dbkey10: int = -1
    source_file_type: int = 0
    status_1: str = ""
    status_2: str = ""
    status_3: str = ""
    date_created: int = 0
    date_modified: int = 0
    date_pending: int = 0
    date_effective: int = 0
    date_finished: int = 0
    date_1: int = 0
    date_2: int = 0
    date_3: int = 0
    created_by: str = ""
    modified_by: str = ""
    floor_bitmap_id: str = ""
    door_transparency: float = 0.5
    floor_tile_width: float = 12
    floor_tile_depth: float = 12
    inventory_model_manual: int = 0
    inventory_model_case_multiple: int = 1
    inventory_model_days_supply: int = 1
    inventory_model_peak: int = 0
    inventory_model_min_units: int = 0
    inventory_model_max_units: int = 0
    case_multiple: float = 1.0
    days_supply: int = 2
    demand_cycle_length: int = 1
    peak_safety_factor: int = 1
    backroom_stock: int = 0
    demand_1: int = 0
    demand_2: int = 0
    demand_3: int = 0
    demand_4: int = 0
    demand_5: int = 0
    demand_6: int = 0
    demand_7: int = 0
    delivery_schedule: str = ""
    id: str = ""
    department: str = ""
    partid: str = ""
    gln: str = ""
    planogram_guid: str = ""
    dbguid: str = ""
    abbrev_name: str = ""
    category: str = ""
    subcategory: str = ""
    source: int = 0
    allocation_group: str = ""
    allocation_sequence: int = 0
    allocation_target_min: int = 0
    allocation_target_max: int = 0
    can_segment: int = 1
    can_split: int = -1
    pg_status: int = -1
    pg_score_percent: int = 0
    pg_score_note: str = ""
    pg_warnings_count: int = 0
    pg_errors_count: int = 0
    pg_action_list: str = ""
    pg_max_stage_reduce: int = 0
    pg_max_stage_fill_out: int = 0
    pg_type: int = 0
    model_filename: str = ""
    dbfamilykey: int = -1
    dbreplacekey: int = -1
    dbversionkey: int = -1
    dbparentpgauxtemplatekey: int = -1
    dbparentpgsourcekey: int = -1
    dbparentpgtemplatekey: int = -1
    dbpgtimedone: int = 0
    pg_server_name: str = ""
    pr_status: int = -1
    movement_period: int = 0
    allocation_section_splits: int = 1
    allocation_priority: int = 0
    checksum_1: int = 0
    checksum_2: int = 0
    checksum_3: int = 0
    checksum_4: int = 0
    checksum_5: int = 0
    use_as_subplanogram: int = 0
    allocation_merge: str = ""
    is_merged: int = 0
    inventory_model_demand_mean_variance: int = -1
    service_level: int = 0
    pg_results_1: int = 0
    pg_results_2: int = 0
    pg_results_3: int = 0
    pg_results_4: int = 0
    pg_results_5: int = 0


class PSAItemError(Exception):
    """Base exception for PSAItem"""


@dataclass
class PSAFixture(PSAItem):
    fixture: str = "Fixture"
    type: int = 0
    name: str = "Shelf"
    key: str = ""
    x: float = 0.0
    width: float = 0.0
    y: float = 0.0
    height: float = 0.0
    z: float = 0.0
    depth: float = 0.0
    slope: float = 0.0
    angle: float = 0.0
    roll: float = 0.0
    color: str = "8421504"
    assembly: str = ""
    x_spacing: float = 0.0
    y_spacing: float = 0.0
    x_start: float = 0.0
    y_start: float = 0.0
    wall_width: float = 0.0
    wall_height: float = 0.0
    wall_depth: float = 0.0
    curve: float = 0.0
    merch: float = 0.0
    check_other_fixtures: int = 1
    check_other_positions: int = 0
    can_obstruct: int = 1
    left_overhang: int = 0
    right_overhang: int = 0
    lower_overhang: int = 0
    upper_overhang: int = 0
    back_overhang: int = 0
    front_overhang: int = 0
    default_merch_style: int = 0
    divider_width: int = 0
    divider_height: int = 0
    divider_depth: int = 0
    can_combine: int = 0
    grille_height: float = 0.0
    notch_offset: float = 0.0
    x_spacing_2: float = 0.0
    x_start_2: float = 0.0
    peg_drop: float = 0.0
    peg_gap_x: float = 0.0
    peg_gap_y: float = 0.0
    primary_fixture_label_format_name: str = ""
    secondary_fixture_label_format_name: str = ""
    shape_id: str = ""
    bitmap_id: str = ""
    merchxmin: int = -1
    merchxmax: int = -1
    merchxuprights: int = -1
    merchxcaps: int = -1
    merchxplacement: int = 0
    merchxnumber: int = 0
    merchxsize: float = 0
    merchxdirection: int = -1
    merchxsqueeze: int = -1
    merchymin: int = -1
    merchymax: int = 0
    merchyuprights: int = -1
    merchycaps: int = -1
    merchyplacement: int = 2
    merchynumber: int = 3
    merchysize: int = 1
    merchydirection: int = 0
    merchysqueeze: int = -1
    merchzmin: int = -1
    merchzmax: int = -1
    merchzuprights: int = -1
    merchzcaps: int = -1
    merchzplacement: int = 2
    merchznumber: int = 3
    merchzsize: int = 1
    merchzdirection: int = 1
    merchzsqueeze: int = -1
    desc_1: str = ""
    desc_2: str = ""
    desc_3: str = ""
    desc_4: str = ""
    desc_5: str = ""
    desc_6: str = ""
    desc_7: str = ""
    desc_8: str = ""
    desc_9: str = ""
    desc_10: str = ""
    desc_11: str = ""
    desc_12: str = ""
    desc_13: str = ""
    desc_14: str = ""
    desc_15: str = ""
    desc_16: str = ""
    desc_17: str = ""
    desc_18: str = ""
    desc_19: str = ""
    desc_20: str = ""
    desc_21: str = ""
    desc_22: str = ""
    desc_23: str = ""
    desc_24: str = ""
    desc_25: str = ""
    desc_26: str = ""
    desc_27: str = ""
    desc_28: str = ""
    desc_29: str = ""
    desc_30: str = ""
    value_1: float = 0.0
    value_2: float = 0.0
    value_3: float = 0.0
    value_4: float = 0.0
    value_5: float = 0.0
    value_6: float = 0.0
    value_7: float = 0.0
    value_8: float = 0.0
    value_9: float = 0.0
    value_10: float = 0.0
    value_11: float = 0.0
    value_12: float = 0.0
    value_13: float = 0.0
    value_14: float = 0.0
    value_15: float = 0.0
    value_16: float = 0.0
    value_17: float = 0.0
    value_18: float = 0.0
    value_19: float = 0.0
    value_20: float = 0.0
    value_21: float = 0.0
    value_22: float = 0.0
    value_23: float = 0.0
    value_24: float = 0.0
    value_25: float = 0.0
    value_26: float = 0.0
    value_27: float = 0.0
    value_28: float = 0.0
    value_29: float = 0.0
    value_30: float = 0.0
    flag_1: int = 0
    flag_2: int = 0
    flag_3: int = 0
    flag_4: int = 0
    flag_5: int = 0
    flag_6: int = 0
    flag_7: int = 0
    flag_8: int = 0
    flag_9: int = 0
    flag_10: int = 0
    location_id: int = 1
    fill_pattern: int = 0
    model_filename: str = ""
    weight_capacity: int = 0
    changed: int = 1
    divider_at_start: int = 0
    divider_at_end: int = 0
    dividers_between_facings: int = 0
    transparency: int = 0
    hide_if_printing: int = 0
    product_association: str = ""
    partid: str = ""
    hide_view_dimensions: int = 1
    gln: str = ""
    # custom_data: str = ""
    can_attach: int = 0
    attached_to_fixture: str = "<None>"
    is_attached: int = 0
    rank_x: int = -1
    rank_y: int = -1
    rank_z: int = -1
    fixture_guid: str = ""
    extra_1: int = 0
    extra_2: int = 0
    extra_3: int = 0

    @property
    def assembly_type(self) -> str:
        return self.assembly.rsplit(" - ", 1)[0].strip()

    @property
    def assembly_index(self) -> int:
        value = self.assembly.rsplit(" - ", 1)[-1].strip()
        if value.isdigit():
            return int(value)

        return 0

    @assembly_index.setter
    def assembly_index(self, value: int) -> None:
        self.assembly = f"{self.assembly_type} - {value}"

    @property
    def type_str(self) -> str:
        if self.type == 0:
            return "REGULAR"
        return "HANGCELL"

    @property
    def shelf_type(self) -> PSAFixtureType:
        try:
            return PSAFixtureType(self.type)
        except ValueError:
            pass

        return PSAFixtureType.OBSTRUCTION

    def to_box(self) -> Box:
        return Box(
            x=self.x,
            y=self.y,
            z=self.z,
            width=self.width,
            height=self.height,
            depth=self.depth,
        )


class PSAFixtureType(enum.IntEnum):
    REGULAR = 0
    HANGCELL = 6
    PEGBOARD = 7
    OBSTRUCTION = 10
    TEXTBOX = 13


@dataclass
class PSASegment(PSAItem):
    segment: str = "Segment"
    name: str = ""
    key: str = ""
    x: float = 0.0
    width: float = 0.0
    y: float = 0.0
    height: float = 0.0
    z: float = 0.0
    depth: float = 0.0
    angle: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    door: int = 0
    door_direction: int = 0
    desc_1: str = ""
    desc_2: str = ""
    desc_3: str = ""
    desc_4: str = ""
    desc_5: str = ""
    desc_6: str = ""
    desc_7: str = ""
    desc_8: str = ""
    desc_9: str = ""
    desc_10: str = ""
    value_1: float = 0.0
    value_2: float = 0.0
    value_3: float = 0.0
    value_4: float = 0.0
    value_5: float = 0.0
    value_6: float = 0.0
    value_7: float = 0.0
    value_8: float = 0.0
    value_9: float = 0.0
    value_10: float = 0.0
    flag_1: int = 0
    flag_2: int = 0
    flag_3: int = 0
    flag_4: int = 0
    flag_5: int = 0
    flag_6: int = 0
    flag_7: int = 0
    flag_8: int = 0
    flag_9: int = 0
    flag_10: int = 0
    frame_width: float = 0.0
    frame_height: float = 0.0
    changed: int = 0
    frame_color: int = -1
    frame_fill_pattern: int = 0
    partid: str = ""
    gln: str = ""
    # custom_data: =
    can_separate: int = 0


def get_segment_index(x: float, _segments: t.List) -> int:
    if isinstance(x, tuple):
        x = tuple_to_float(t=x)

    _segments_length = len(_segments)
    if x < _segments[0]["bay_x"]:
        return 0

    for index, _segment in enumerate(_segments):
        if index + 1 < _segments_length:
            current_bay_x = float(_segment["bay_x"])
            next_bay_x = float(_segments[index + 1]["bay_x"])
            if current_bay_x <= x < next_bay_x:
                return index
        else:
            return index

    return 0


def get_item_fixture_index(
    bay_no: int, prod_y: float, shelf_list: t.List[t.Any]
) -> int:
    if isinstance(prod_y, tuple):
        prod_y = tuple_to_float(t=prod_y)

    shelf_list_clone = list(
        filter(lambda x: (x["segment_index"] == bay_no), shelf_list)
    )
    shelf_list_clone.sort(key=lambda x: x["shelf_y"])
    shelf_length = len(shelf_list_clone)
    located_shelf = {}
    for index, shelf in enumerate(shelf_list_clone):
        if index + 1 < shelf_length:
            current_shelf_y = float(shelf["shelf_y"])
            next_shelf_y = float(shelf_list_clone[index + 1]["shelf_y"])
            if current_shelf_y <= prod_y < next_shelf_y:
                located_shelf = shelf
                break
        else:
            located_shelf = shelf
            break

    if not located_shelf:
        return -1

    return next(
        (
            i
            for i, item in enumerate(shelf_list)
            if (
                item["shelf_x"] == located_shelf["shelf_x"]
                and item["shelf_y"] == located_shelf["shelf_y"]
            )
        ),
        -1,
    )


def tuple_to_float(t: tuple) -> float:
    return float(".".join(str(elem) for elem in t))


def find_highest_item(items: t.List[t.Dict[str, t.Any]]) -> int:
    return max((i["height"] for i in items), default=0)


def value_to_csv(value: t.Any) -> str:
    if value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")

    return str(value)


@dataclass
class Box:
    """A box in 3D space"""

    x: float
    y: float
    z: float
    width: float
    height: float
    depth: float

    def merge(self, other: Box) -> Box:
        """Merge two boxes into one"""
        x = min(self.x, other.x)
        y = min(self.y, other.y)
        z = min(self.z, other.z)
        w = max(self.x + self.width, other.x + other.width) - x
        h = max(self.y + self.height, other.y + other.height) - y
        d = max(self.z + self.depth, other.z + other.depth) - z
        return self.__class__(x, y, z, w, h, d)

    def does_overlap(self, other: Box) -> bool:
        "Check if two boxes overlap."
        return (
            self.x < other.x + other.width
            and self.x + self.width > other.x
            and self.y < other.y + other.height
            and self.y + self.height > other.y
            and self.z < other.z + other.depth
            and self.z + self.depth > other.z
        )
