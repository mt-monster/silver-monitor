from backend.config import OZ_TO_G, OZ_TO_KG
from backend.state import state


def get_conv():
    return state.usd_cny_cache["rate"] * OZ_TO_KG


def get_conv_gold():
    return state.usd_cny_cache["rate"] * OZ_TO_G
