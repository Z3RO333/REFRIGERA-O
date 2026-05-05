from pydantic import BaseModel, ConfigDict


class BriseVariables(BaseModel):
    model_config = ConfigDict(extra="ignore")

    state: bool | None = None
    temperature: float | None = None
    humidity: float | None = None       # API retorna float (ex: 47.5)
    consumption: float | None = None
    consumptionEstimated: float | None = None


class BriseParameters(BaseModel):
    model_config = ConfigDict(extra="ignore")

    modeDevice: int | None = None
    modeAC: int | None = None
    fanSpeed: int | None = None
    setpointCool: int | None = None
    setpointHeat: int | None = None
    ecoCool: int | None = None
    ecoHeat: int | None = None


class BriseConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    timeZone: int | None = None
    groupLevel1: str | None = None
    groupLevel2: str | None = None
    groupLevel3: str | None = None
    groupLevel4: str | None = None
    btu: int | None = None
    logDay: int | None = None
    pulseKw: int | None = None
    enableFan: bool | None = None
    enableHeat: bool | None = None
    dnd: bool | None = None


class BriseDevice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    deviceId: int
    deviceUser: str | None = None
    devicePassword: str | None = None
