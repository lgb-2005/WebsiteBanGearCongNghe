"""Read the server-authorized snapshot; the model cannot select another customer."""
from copy import deepcopy
from analytics.ml.purchase_intent import unavailable_payload


def get_customer_purchase_intent(ctx=None):
    return deepcopy(ctx.purchase_intent if ctx and ctx.purchase_intent else unavailable_payload())
