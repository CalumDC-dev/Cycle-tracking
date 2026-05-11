"""Small XLSX table reader using only the Python standard library."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import os
import re
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {"main": MAIN, "r": R, "rel": PKG_REL}


@dataclass(frozen=True)
class TableDef:
    name: str
    sheet_name: str
    sheet_path: str
    table_path: str
    ref: str
    columns: list[str]


def _col_to_idx(col: str) -> int:
    value = 0
    for char in col:
        value = value * 26 + ord(char) - 64
    return value


def _split_addr(cell_ref: str) -> tuple[int, int]:
    match = re.match(r"^([A-Z]+)(\d+)$", cell_ref)
    if not match:
        raise ValueError(f"Unsupported cell ref: {cell_ref}")
    return _col_to_idx(match.group(1)), int(match.group(2))


def _parse_range(ref: str) -> tuple[int, int, int, int]:
    start, end = ref.split(":") if ":" in ref else (ref, ref)
    c1, r1 = _split_addr(start)
    c2, r2 = _split_addr(end)
    return min(c1, c2), min(r1, r2), max(c1, c2), max(r1, r2)


def excel_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    serial = float(value)
    # Excel's Windows date system includes the fictional 1900-02-29.
    origin = date(1899, 12, 30)
    return (origin + timedelta(days=serial)).isoformat()


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def integer(value: Any) -> int | None:
    num = number(value)
    if num is None:
        return None
    return int(round(num))


class XlsxTableReader:
    def __init__(self, path: str):
        self.path = path
        self.zip = ZipFile(path)
        self.shared_strings = self._load_shared_strings()
        self.sheets = self._load_sheets()
        self.tables = self._load_tables()

    def close(self) -> None:
        self.zip.close()

    def __enter__(self) -> "XlsxTableReader":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def read_table(self, table_name: str) -> list[dict[str, Any]]:
        table = self.tables[table_name]
        sheet = ET.fromstring(self.zip.read(table.sheet_path))
        c1, r1, c2, r2 = _parse_range(table.ref)
        cell_values: dict[tuple[int, int], Any] = {}
        for row in sheet.findall("main:sheetData/main:row", NS):
            row_idx = int(row.attrib["r"])
            if row_idx < r1 or row_idx > r2:
                continue
            for cell in row.findall("main:c", NS):
                col_idx, _ = _split_addr(cell.attrib["r"])
                if c1 <= col_idx <= c2:
                    cell_values[(col_idx, row_idx)] = self._cell_value(cell)

        rows: list[dict[str, Any]] = []
        for row_idx in range(r1 + 1, r2 + 1):
            record = {}
            for offset, column in enumerate(table.columns):
                record[column] = cell_values.get((c1 + offset, row_idx))
            rows.append(record)
        return rows

    def _load_shared_strings(self) -> list[str]:
        if "xl/sharedStrings.xml" not in self.zip.namelist():
            return []
        root = ET.fromstring(self.zip.read("xl/sharedStrings.xml"))
        strings = []
        for item in root.findall("main:si", NS):
            strings.append("".join(text.text or "" for text in item.findall(".//main:t", NS)))
        return strings

    def _load_sheets(self) -> dict[str, str]:
        workbook = ET.fromstring(self.zip.read("xl/workbook.xml"))
        rels_root = ET.fromstring(self.zip.read("xl/_rels/workbook.xml.rels"))
        rels = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels_root.findall("rel:Relationship", NS)}
        sheets = {}
        for sheet in workbook.findall("main:sheets/main:sheet", NS):
            rel_id = sheet.attrib[f"{{{R}}}id"]
            sheets[sheet.attrib["name"]] = os.path.normpath(f"xl/{rels[rel_id]}").replace("\\", "/")
        return sheets

    def _load_tables(self) -> dict[str, TableDef]:
        tables: dict[str, TableDef] = {}
        for sheet_name, sheet_path in self.sheets.items():
            rel_path = f"{os.path.dirname(sheet_path)}/_rels/{os.path.basename(sheet_path)}.rels"
            if rel_path not in self.zip.namelist():
                continue
            rels_root = ET.fromstring(self.zip.read(rel_path))
            for rel in rels_root.findall("rel:Relationship", NS):
                if not rel.attrib["Type"].endswith("/table"):
                    continue
                table_path = os.path.normpath(os.path.join(os.path.dirname(sheet_path), rel.attrib["Target"])).replace("\\", "/")
                table_root = ET.fromstring(self.zip.read(table_path))
                columns = [
                    column.attrib["name"]
                    for column in table_root.findall("main:tableColumns/main:tableColumn", NS)
                ]
                table = TableDef(
                    name=table_root.attrib["name"],
                    sheet_name=sheet_name,
                    sheet_path=sheet_path,
                    table_path=table_path,
                    ref=table_root.attrib["ref"],
                    columns=columns,
                )
                tables[table.name] = table
        return tables

    def _cell_value(self, cell: ET.Element) -> Any:
        cell_type = cell.attrib.get("t")
        if cell_type == "s":
            value = cell.find("main:v", NS)
            if value is None or value.text is None:
                return None
            return self.shared_strings[int(value.text)]
        if cell_type == "inlineStr":
            return "".join(text.text or "" for text in cell.findall(".//main:t", NS))
        if cell_type == "b":
            value = cell.find("main:v", NS)
            return value is not None and value.text == "1"

        value = cell.find("main:v", NS)
        if value is None or value.text is None:
            return None
        text = value.text
        if re.match(r"^-?\d+(\.\d+)?([Ee][+-]?\d+)?$", text):
            return float(text)
        return text

