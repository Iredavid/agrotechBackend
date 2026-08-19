import pandas as pd

df = pd.read_csv("/mnt/user-data/uploads/nigerian_agriculture_seasonal_crop_yields.csv")

# Quality grade -> numeric score for aggregation
grade_score = {"Grade A": 3, "Grade B": 2, "Grade C": 1}
df["grade_score"] = df["quality_grade"].map(grade_score)

state_crop = (
    df.groupby(["state", "crop"])
    .agg(
        avg_yield_t_ha=("yield_t_ha", "mean"),
        median_yield_t_ha=("yield_t_ha", "median"),
        total_production_t=("production_t", "sum"),
        records=("crop", "count"),
        avg_grade_score=("grade_score", "mean"),
    )
    .reset_index()
)

# Rank crops within each state by total historical production (proxy for how
# dominant/proven that crop is in that state)
state_crop["state_rank"] = (
    state_crop.groupby("state")["total_production_t"]
    .rank(ascending=False, method="min")
)

state_crop = state_crop.sort_values(["state", "state_rank"])
state_crop.to_csv("state_crop_lookup.csv", index=False)

print(state_crop.head(16))
print()
print("Total state-crop combos:", len(state_crop))
print("States covered:", state_crop['state'].nunique())

# Sanity check: top crop per state, a few examples
print()
for s in ["Kano", "Rivers", "Ekiti", "FCT", "Benue"]:
    sub = state_crop[state_crop["state"] == s].sort_values("state_rank")
    print(f"\n{s} top crops by production:")
    print(sub[["crop","avg_yield_t_ha","total_production_t","records","state_rank"]].head(3).to_string(index=False))
