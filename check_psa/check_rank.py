from itertools import pairwise


def check_rank(psa, product_priority):
    ranged_items = {p[1] for p in psa if p[0] == "Position"}
    for a, b in pairwise(product_priority):
        if a not in ranged_items and b in ranged_items:
            yield (a, b)
