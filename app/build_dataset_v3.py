"""
v3: adds soil_texture as a categorical feature (Sandy / Loamy / Clay), derived
from ISRIC SoilGrids clay%/sand% -- same data source already used for pH/organic
carbon, so no new API integration needed on the fetch side.

Texture assigned per crop using real agronomic preference (not random):
  - yam: MUST have loose, friable, well-drained soil -> almost entirely Loamy,
    small Sandy tail, essentially never Clay (compacted soil deforms tubers)
  - rice (paddy): needs water-retentive soil -> mostly Clay/Loamy, rarely Sandy
  - cassava, millet, sorghum: tolerate/prefer lighter soils -> Sandy/Loamy mix
  - cocoa, oil_palm, maize: general loamy preference with some tolerance
"""
import numpy as np
import pandas as pd

np.random.seed(42)
N_PER_CROP = 150

AGRONOMIC_RANGES_MGKG = {
    "maize":     dict(N=(600, 1200), P=(8, 25),  K=(80, 180),  temperature=(18, 28),
                       humidity=(55, 75), ph=(5.5, 7.0), rainfall=(60, 110)),
    "rice":      dict(N=(700, 1300), P=(10, 30), K=(60, 150),  temperature=(20, 27),
                       humidity=(78, 85), ph=(5.0, 7.5), rainfall=(180, 300)),
    "cassava":   dict(N=(300, 700),  P=(5, 20),  K=(150, 300), temperature=(25, 32),
                       humidity=(55, 80), ph=(5.0, 6.8), rainfall=(140, 220)),
    "cocoa":     dict(N=(500, 1000), P=(8, 25),  K=(180, 320), temperature=(23, 28),
                       humidity=(75, 90), ph=(5.8, 7.0), rainfall=(230, 300)),
    "millet":    dict(N=(200, 500),  P=(3, 12),  K=(30, 90),   temperature=(27, 36),
                       humidity=(25, 55), ph=(5.5, 7.8), rainfall=(35, 90)),
    "oil_palm":  dict(N=(600, 1100), P=(10, 28), K=(200, 350), temperature=(25, 32),
                       humidity=(78, 92), ph=(4.3, 6.3), rainfall=(250, 300)),
    "sorghum":   dict(N=(250, 550),  P=(4, 15),  K=(40, 110),  temperature=(26, 35),
                       humidity=(30, 60), ph=(5.5, 8.3), rainfall=(45, 100)),
    "yam":       dict(N=(400, 800),  P=(8, 22),  K=(200, 320), temperature=(25, 30),
                       humidity=(60, 80), ph=(5.5, 6.7), rainfall=(140, 220)),
}

# P(texture) per crop -- must sum to 1, order = [Sandy, Loamy, Clay]
TEXTURE_DIST = {
    "maize":    [0.20, 0.65, 0.15],
    "rice":     [0.05, 0.40, 0.55],   # paddy prefers water-retentive clay/loam
    "cassava":  [0.40, 0.55, 0.05],   # tolerates sandy well, avoid heavy clay
    "cocoa":    [0.05, 0.65, 0.30],
    "millet":   [0.60, 0.38, 0.02],   # Sahel sandy soils
    "oil_palm": [0.10, 0.50, 0.40],
    "sorghum":  [0.55, 0.42, 0.03],
    "yam":      [0.15, 0.80, 0.05],   # needs loose loamy soil, clay is bad for tubers
}
TEXTURE_CLASSES = ["Sandy", "Loamy", "Clay"]

def make_synthetic(crop, ranges, texture_probs, n=N_PER_CROP):
    rows = {}
    for feat, (lo, hi) in ranges.items():
        rows[feat] = np.round(np.random.uniform(lo, hi, n), 2)
    rows["soil_texture"] = np.random.choice(TEXTURE_CLASSES, size=n, p=texture_probs)
    df = pd.DataFrame(rows)
    df["label"] = crop
    return df

frames = [make_synthetic(c, r, TEXTURE_DIST[c]) for c, r in AGRONOMIC_RANGES_MGKG.items()]
full = pd.concat(frames, ignore_index=True)
full = full.sample(frac=1, random_state=42).reset_index(drop=True)
full.to_csv("nigeria_crop_training_data_v3.csv", index=False)

print(full["label"].value_counts())
print(pd.crosstab(full["label"], full["soil_texture"]))
