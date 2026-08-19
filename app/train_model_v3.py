import pandas as pd
from catboost import CatBoostClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import accuracy_score, classification_report
import joblib

df = pd.read_csv("nigeria_crop_training_data_v3.csv")
feature_cols = ["N", "P", "K", "temperature", "humidity", "ph", "rainfall", "soil_texture"]
cat_features = ["soil_texture"]

X = df[feature_cols]
y = df["label"]

le = LabelEncoder()
y_enc = le.fit_transform(y)

X_train, X_test, y_train, y_test = train_test_split(
    X, y_enc, test_size=0.2, random_state=42, stratify=y_enc
)

model = CatBoostClassifier(
    iterations=400, depth=6, learning_rate=0.08,
    loss_function="MultiClass", eval_metric="Accuracy",
    cat_features=cat_features,
    random_seed=42, verbose=False,
)
model.fit(X_train, y_train, eval_set=(X_test, y_test))

preds = model.predict(X_test).flatten()
print(f"Test accuracy: {accuracy_score(y_test, preds):.4f}")
print(classification_report(y_test, preds, target_names=le.classes_))

from sklearn.model_selection import StratifiedKFold
skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
fold_accs = []
for train_idx, test_idx in skf.split(X, y_enc):
    m = CatBoostClassifier(iterations=400, depth=6, learning_rate=0.08,
                            loss_function="MultiClass", cat_features=cat_features,
                            verbose=False, random_seed=42)
    m.fit(X.iloc[train_idx], y_enc[train_idx])
    p = m.predict(X.iloc[test_idx]).flatten()
    fold_accs.append(accuracy_score(y_enc[test_idx], p))
import numpy as np
print(f"5-fold CV accuracy: {np.mean(fold_accs):.4f} (+/- {np.std(fold_accs):.4f})")

print("\nFeature importance:")
for name, imp in sorted(zip(feature_cols, model.get_feature_importance()), key=lambda x: -x[1]):
    print(f"  {name}: {imp:.1f}")

model.save_model("catboost_nigeria_crop_model_v3.cbm")
joblib.dump(le, "label_encoder_v3.pkl")
joblib.dump(feature_cols, "feature_columns_v3.pkl")
joblib.dump(cat_features, "cat_features_v3.pkl")
print("\nSaved v3 model (with soil_texture).")
