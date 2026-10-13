# SafeCross AI

SafeCross AI ranks New York City intersections by **relative crash risk** and compares walking, cycling and driving
routes by the risk of the intersections they pass through. It also has a Westchester County transfer area that has
**not been validated**. Scores are relative to the area (a percentile and an index against the area average), not a
predicted number of crashes, and the app is a student capstone project, not a safety tool.

## What is in this repository

| Folder | What it is |
|---|---|
| `app/` | Streamlit app (Explore map and Route finder) and the shared scoring code |
| `pwa/` | Installable web app (Flask server plus a browser front end) with the same features |
| `scripts/` | Build scripts for the street-name table, Westchester assets and the model bundle |
| `notebooks/` | The three notebooks that acquire the data, train and evaluate the models (add them here) |

## What is not in this repository

Trained models, crash data, street graphs and API keys are left out on purpose (see `.gitignore`).
To run the app you need to create them:

1. Run the notebooks in order to download and clean the data and train the model.
2. Run `python scripts/make_model_bundle.py` and `python scripts/export_streamlit_assets.py` to create
   `models/safecross_model_bundle.joblib`, `models/safecross_model_metadata.json` and `data/sample/safecross_app_demo.csv`.
3. Run `python scripts/build_intersection_info.py` to create `data/sample/intersection_info.csv` (street names and facts).
   This step needs `osmnx`.

## Run the Streamlit app

```
pip install -r requirements.txt
streamlit run app/streamlit_app.py
```

Route finding needs two Google Maps Platform keys. See [ROUTE_FINDER_SETUP.md](ROUTE_FINDER_SETUP.md).
Put them in `.streamlit/secrets.toml` (never commit that file).

## Run the web app (PWA)

```
pip install -r pwa/requirements.txt
python pwa/server/server.py
```

Details, including how to share it from your own PC or host it on a server:
[pwa/README_PWA.md](pwa/README_PWA.md), [pwa/TUNNEL_SETUP.md](pwa/TUNNEL_SETUP.md), [pwa/deploy/DEPLOY_VPS.md](pwa/deploy/DEPLOY_VPS.md).

## How the route score works

For each route, every intersection near the path adds `closeness x vulnerability x risk index`. The risk index is the
model's predicted risk divided by the area average. For walking and cycling, vulnerability rises with the posted
speed and with recent pedestrian or cyclist casualty crashes. The weights are judgement calls, not fitted values.
The route with the lowest score is recommended, and routes within 5% of each other are treated as equal.

## Westchester

The model is trained on NYC. Westchester results are a transfer test and are not validated. See
[WESTCHESTER_TRANSFER.md](WESTCHESTER_TRANSFER.md).

## Limits

Crash records show where crashes were reported, not how dangerous a place is for each person. OpenStreetMap tags such
as sidewalks are often missing, and "not mapped" does not mean "none". Do not use this to make safety decisions.
