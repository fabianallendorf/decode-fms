from typing import Dict, List

from src.dataclasses import FormItem, FormItemMetadata, Form

FormID = str
FormItems = Dict[FormID, FormItem]
FormMetadata = Dict[FormID, FormItemMetadata]
SearchResults = Dict[int, Form]
UpdatePayload = Dict[str, str]
