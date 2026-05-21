from pydantic import BaseModel, StrictBool


class KillSwitchUpdate(BaseModel):
    active: StrictBool = True
