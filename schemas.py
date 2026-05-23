from typing import Optional

from pydantic import BaseModel


class UserCreate(BaseModel):
    name: str
    phone: str
    role: Optional[str] = "user"
    business_category: Optional[str] = None
    business_type: Optional[str] = None
    business_type_label: Optional[str] = None


class CustomerCreate(BaseModel):
    owner_phone: str
    name: str
    customer_phone: Optional[str] = None
