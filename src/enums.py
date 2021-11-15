from enum import Enum


class ItemType(Enum):
    CHECKBOX = "checkbox"
    TEXT = "text"
    SELECT = "select"


class FormValueType(Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
