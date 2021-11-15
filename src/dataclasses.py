from dataclasses import dataclass
from typing import Optional

from src.enums import ItemType, FormValueType


@dataclass
class FormItem:
    page: int
    form_number: str
    form_id: str
    input_type: ItemType
    comment: Optional[str] = None


@dataclass
class FormItemMetadata:
    value_type: FormValueType
    mandatory: bool
    triggers_change: bool
    checkbox_group: Optional[str]
    min_length: Optional[int]
    max_length: Optional[int]
    regex: Optional[str]
    date_format: Optional[str]


@dataclass
class Form:
    form_id: str
    form_path: str
    display_name: str

    def __str__(self):
        return self.display_name
