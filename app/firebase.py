from pathlib import Path

from fastapi import HTTPException
from firebase_admin import auth
from firebase_admin import credentials
import firebase_admin
from firebase_admin import firestore


BASE_DIR = Path(__file__).resolve().parent.parent

firebase_key_path = BASE_DIR / "firebaseServiceAccountKey.json"

cred = credentials.Certificate(firebase_key_path)
app = firebase_admin.initialize_app(cred)
db = firestore.client()


def addUserData(data, userId, farmName):
    try:
        db.collection("users").document(userId).set({
            "farmData": data,
            "farmName": farmName,
        })
        # return userId
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


async def getUserData(userId):
    from app.crop_service import get_crop_recommendation
    try:
        doc_ref = db.collection("users").document(userId)

        doc = doc_ref.get()
        if doc.exists:
            user_data = doc.to_dict()
            farmData = user_data.get("farmData", {})
            farmName = user_data.get("farmName", {})
            aiPredict = await get_crop_recommendation(**farmData)
            return {
                "farmName": farmName,
                **aiPredict,
                **farmData
            }

        else:
            raise HTTPException(status_code=404, detail="No such document")
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )

# 

# async def addStates():
#     try:
#         db.collection("soil_texture_options").document("soil_texture_options").set({
#             "soil_texture_options": TEXTURE_OPTIONS
#         })
#         return "Soil texture options added successfully"
#     except Exception as error:
#         raise HTTPException(
#             status_code=500,
#             detail=str(error),
#         )
def get_texture_options() -> list[dict]:
    try:
        doc_ref = db.collection("soil_texture_options").document(
            "soil_texture_options")

        doc = doc_ref.get()
        if doc.exists:
            texture_data = doc.to_dict()
            TEXTURE_OPTIONS = texture_data.get("soil_texture_options", [])
            return TEXTURE_OPTIONS

        else:
            raise HTTPException(status_code=404, detail="No such document")
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )

def get_irrigation_options() -> list[dict]:
    try:
        doc_ref = db.collection("irrigation_options").document(
            "irrigation_options")

        doc = doc_ref.get()
        if doc.exists:
            irrigation_data = doc.to_dict()
            IRRIGATION_OPTIONS = irrigation_data.get("irrigation_options", [])
            return IRRIGATION_OPTIONS

        else:
            raise HTTPException(status_code=404, detail="No such document")
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )


def get_state_list() -> list[dict]:
    try:
        doc_ref = db.collection("states").document("states")

        doc = doc_ref.get()
        if doc.exists:
            state_data = doc.to_dict()
            return state_data.get("states", [])

        else:
            raise HTTPException(status_code=404, detail="No such document")
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=str(error),
        )
