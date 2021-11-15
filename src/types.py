from typing import Dict

from src.dataclasses import FormItem, FormItemMetadata, Form

FormID = str
FormItems = Dict[FormID, FormItem]
FormMetadata = Dict[FormID, FormItemMetadata]
SearchResults = Dict[int, Form]
