def fertilityScore(nutrient):

    def score_nitrogen(n):
        if n is None:
            return 0
        elif n < 200:
            return 20
        elif n < 400:
            return 50
        elif n < 800:
            return 80
        elif n <= 1200:
            return 100
        else:
            return 80

    def score_phosphorus(p):
        if p is None:
            return 0
        elif p < 5:
            return 20
        elif p < 10:
            return 50
        elif p < 20:
            return 80
        elif p <= 40:
            return 100
        else:
            return 90

    def score_potassium(k):
        if k is None:
            return 0
        elif k < 40:
            return 20
        elif k < 80:
            return 50
        elif k < 150:
            return 80
        elif k <= 300:
            return 100
        else:
            return 90

    nitrogen_score = score_nitrogen(
        nutrient.get("nitrogen")
    )

    phosphorus_score = score_phosphorus(
        nutrient.get("phosphorus")
    )

    potassium_score = score_potassium(
        nutrient.get("potassium")
    )

    fertility_score = (
        nitrogen_score * 0.40
        + phosphorus_score * 0.30
        + potassium_score * 0.30
    )

    return round(fertility_score, 2)


def calculate_ph_score(ph):
    # Guard: ph can be None if SoilGrids has no data for this point
    if ph is None:
        return None

    ideal_min = 6.0
    ideal_max = 7.0

    if ideal_min <= ph <= ideal_max:
        return 100

    if ph < ideal_min:
        distance = ideal_min - ph
    else:
        distance = ph - ideal_max

    score = 100 - (distance * 30)

    return max(
        0,
        min(100, score)
    )


def calculate_moisture_score(moisture_percent):
    # Guard: moisture_percent can be None if underlying SMAP bands are missing
    if moisture_percent is None:
        return None

    if moisture_percent < 10:
        return 30
    elif moisture_percent < 20:
        return 60
    elif moisture_percent < 35:
        return 100
    elif moisture_percent < 50:
        return 75
    else:
        return 50


def calculate_water_balance_score(balance):
    # Guard: balance can be None if precipitation/evapotranspiration/runoff missing
    if balance is None:
        return None

    if balance <= -0.1:
        return 20
    elif balance < 0:
        return 50
    elif balance < 0.1:
        return 80
    else:
        return 100


def weighted_average(components: list[tuple]) -> float | None:
    """
    components: list of (value, weight) pairs.
    Skips any component whose value is None, and renormalizes the
    remaining weights so they still sum to 1. Returns None only if
    every component is missing.
    """
    available = [(v, w) for v, w in components if v is not None]
    if not available:
        return None
    total_weight = sum(w for _, w in available)
    if total_weight == 0:
        return None
    return sum(v * w for v, w in available) / total_weight