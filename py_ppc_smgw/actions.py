from enum import Enum


class Action(Enum):
    Login = "login"  # Not used
    Logout = "logout"
    MeterForm = "meterform"
    ShowMeterProfile = "showMeterProfile"
    ExportMeterProfile = "exportMeterProfile"
    SoftwareVersions = "swversions"
    Selftest = "selftest"

    ExportMeterValues = "exportMeterValues"
