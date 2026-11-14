"""Sentences the backend writes into explanations, per language.

English and French are complete. Twi and Hausa: the app's buttons, labels and short texts are
translated in the frontend; these longer generated sentences fall back to English for now (or are
translated by the optional AI explainer). Add a language by copying the "en" block.
Native speakers should review every translation before launch.
"""
from __future__ import annotations

MONTHS = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "fr": ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."],
}
AND = {"en": "and", "fr": "et"}

CRITERIA = {
    "en": {"water": "water fit", "nitrogen": "nitrogen supply", "organic_matter": "organic matter",
           "erosion": "erosion protection", "infiltration": "water soaking in", "pest_break": "pest break",
           "income": "income", "forage": "livestock feed", "climate_fit": "climate fit"},
    "fr": {"water": "adaptation à l'eau", "nitrogen": "apport d'azote", "organic_matter": "matière organique",
           "erosion": "protection contre l'érosion", "infiltration": "infiltration de l'eau",
           "pest_break": "rupture des ravageurs", "income": "revenu", "forage": "fourrage",
           "climate_fit": "adaptation au climat"},
}

T = {
    "en": {
        "cur_start": "This is your starting point. Every suggestion is compared with it.",
        "weakest": "Weakest area: {label} ({score}/100).",
        "ev_bare_rot": "Soil is left bare in {months}",
        "ev_bare_sat": "Satellites see the field bare in {months}",
        "risk_same_family": "The same plant family is grown {n} times in a row, so pests and diseases ({pests}) can build up.",
        "risk_no_n": "No crop adds nitrogen; about {n} kg N/ha a year must come from fertilizer or manure.",
        "why_erosion": "Keeps the soil covered for longer",
        "why_erosion_fill": ", filling the bare gap in {months}",
        "why_storm_months": ". Heavy storms hit most in {months}",
        "ev_heavy": "{n} heavy-rain days a year (top 5% of daily totals, above {mm} mm)",
        "ev_slope": "Average field slope {slope}% ({share}% of the field in the high-erosion zone)",
        "why_nitrogen": "Adds {crops}: legumes whose root nodules fix about {n} kg of nitrogen per hectare a year.",
        "ev_ntable": "Nitrogen fixed per crop (indicative values)",
        "ev_soc": "Topsoil organic carbon {soc} g/kg ({level})",
        "low": "low", "moderate": "moderate",
        "why_om_cover": "{crops} add a lot of plant material to the soil",
        "why_om_deep": "{crops} root deeply (1.5 m or more), opening channels so rain soaks in",
        "why_om_generic": "More crop residue and roots go back into the soil",
        "why_intercrop": "Grows {pairs} together in the same field: the legume adds nitrogen and covers the ground without giving up the main crop.",
        "why_pushpull": "Push-pull: desmodium between the maize rows repels stem borers and fall armyworm and suppresses Striga.",
        "why_infil": "Deep roots, organic matter and cover during storms help rain soak into the soil instead of running off.",
        "why_pest": "Changes plant families ({new} families instead of {old}), breaking the cycle of pests and diseases.",
        "why_water": "Uses rain better: {new}% of the crops' water comes from rain (now {old}%); water shortfall about {mm} mm a year.",
        "ev_et0": "Crop water demand = FAO-56 crop coefficient × reference evapotranspiration (Penman-Monteith)",
        "why_drought": "{crops} cope well with dry spells.",
        "why_income": "Adds crops that sell better locally and spreads income across the year.",
        "why_forage": "Produces more animal feed (forage legumes or crop residues).",
        "why_climate": "Crops are timed so their sensitive stages avoid the hottest and driest months.",
        "ev_dry_months": "Rain covers less than half of crop water demand in {months}",
        "ev_heat_months": "Frequent days above 35°C in {months}",
        "ev_gedi": "Natural vegetation within {km} km holds about {mean} t/ha of biomass, a guide to what this land can grow",
        "ev_esi": "Plants were short of water in {months} (ECOSTRESS evaporative stress index below 0.6)",
        "ev_landsat": "At 30 m, the field is greenest in {month}",
        "ev_events": "{n} natural events recorded within {km} km in the last {years} years (latest: {title})",
        "ev_soiltest": "Your own soil test was used instead of modelled soil values",
        "ev_lapse": "Temperatures adjusted {shift} °C for your field's height ({field} m vs the {grid} m NASA grid average)",
        "gap_norain": "Rain alone cannot grow a crop here: every option assumes the water you said you can give.",
        "benefit_bare": "Bare-soil months a year: {old} → {new}",
        "benefit_n": "Free nitrogen from legumes: about {n} kg N/ha a year (can cut fertilizer cost)",
        "benefit_water": "Water shortfall: {old} → {new} mm a year",
        "benefit_fam": "Plant families in the rotation: {old} → {new}",
        "benefit_score": "{label}: {old} → {new} (out of 100)",
        "benefit_none": "Similar to your current rotation on most measures, with a different crop mix.",
        "risk_lower": "Lower {label} than now ({old} → {new}).",
        "risk_heat": "{when}: heat stress risk (about {days} hot days around flowering).",
        "risk_water": "{when}: may run short of water (about {mm} mm not covered by rain or soil water).",
        "risk_frost": "{when}: frost risk ({days} nights below its damage temperature).",
        "risk_waterlog": "{when}: waterlogging risk in very wet months; needs well-drained ground.",
        "when": "{crop} sown in {month} (year {year})",
        "risk_new": "New to this farm: {crops}. Check seed, know-how and buyers before switching.",
        "risk_pests": "{crop}: watch for {pests}.",
        "risk_perennial": "Perennial forage can be hard to remove when you want the field back for crops.",
        "risk_heat_trend": "Very hot days are increasing here; heat-sensitive stages of {crops} may get riskier.",
        "risk_onset_trend": "The rainy season is starting later over the years; early sowings may need to move.",
        "risk_weak_year": "Weakest in a '{name}' ({pct}% of past years): climate fit drops to {fit}/100.",
        "risk_no_market": "You said there is no buyer nearby for {crops}.",
        "risk_irrigation": "Needs about {mm} mm of extra water a year, more than the water you said you have.",
        "robust_summary": "Holds up in {ok} of {n} kinds of year",
        "gap_demo": "DEVELOPMENT DATA: these numbers are synthetic. Not for real decisions.",
        "gap_power": "Weather is a ~50 km NASA POWER average; your field can be wetter, drier, hotter or cooler.",
        "gap_smap": "SMAP soil moisture is a 9 km average and only exists from 2015.",
        "gap_nosmap": "No satellite soil moisture yet: model soil wetness (NASA POWER) is used instead.",
        "gap_grace": "GRACE water storage covers ~300 km; it shows the regional trend, not your well.",
        "gap_eco_pending": "ECOSTRESS (70 m plant water stress) is still being prepared by NASA; check back later.",
        "gap_traits": "Crop traits and market values are general estimates, not local prices or local varieties.",
        "gap_pests": "Pest and disease pressure, labour and land tenure are not in the data.",
        "gap_soilmodel": "Soil values are modelled (SoilGrids 250 m); a lab soil test is far more reliable.",
        "ask_dates": "Confirm sowing dates and varieties with your extension officer.",
        "ask_seed": "Find seed and buyers for {crops}.",
        "ask_inoculant": "Ask whether the legumes need rhizobium inoculant on your soil.",
        "ask_soiltest": "Do a soil test (pH, N, P, K, organic matter) to confirm the soil assumptions.",
        "ask_market": "Check today's prices for {crops} at your nearest market.",
        "c_demo": "development data", "c_disagree": "rainfall sources disagree",
        "c_agree": "two independent rainfall sources agree", "c_short": "short climate record",
        "c_new_n": "{n} crops new to this farm", "c_limit": "a crop is near its climate limits",
        "c_sensitive": "sensitive to some kinds of year", "c_nondvi": "no satellite vegetation record",
        "c_soiltest": "your soil test was used", "c_eco": "ECOSTRESS plant stress confirms the dry months",
        "summary_current": "Your current rotation, scored with the same rules as the suggestions.",
        "summary": "{seq}. Biggest gains: {gains}. Watch out: {watch}",
        "summary_nothing": "nothing major flagged by the data",
        "balance": "a different balance",
        "headline_rain": "About {mm} mm of rain a year; crops can grow on rain alone in {windows}.",
        "headline_none": "no reliable season",
        "headline_changing": "Changing: {items}.",
        "headline_bare": "Satellites show the field mostly bare in {months}.",
        "fallow": "Fallow", "year_short": "Y",
    },
    "fr": {
        "cur_start": "C'est votre point de départ. Chaque suggestion lui est comparée.",
        "weakest": "Point le plus faible : {label} ({score}/100).",
        "ev_bare_rot": "Le sol reste nu en {months}",
        "ev_bare_sat": "Les satellites voient le champ nu en {months}",
        "risk_same_family": "La même famille de plantes est cultivée {n} fois de suite : ravageurs et maladies ({pests}) peuvent s'installer.",
        "risk_no_n": "Aucune culture n'apporte d'azote ; environ {n} kg N/ha par an doivent venir d'engrais ou de fumier.",
        "why_erosion": "Garde le sol couvert plus longtemps",
        "why_erosion_fill": ", en comblant la période nue de {months}",
        "why_storm_months": ". Les gros orages frappent surtout en {months}",
        "ev_heavy": "{n} jours de forte pluie par an (5 % des jours les plus pluvieux, plus de {mm} mm)",
        "ev_slope": "Pente moyenne du champ {slope} % ({share} % du champ en zone de forte érosion)",
        "why_nitrogen": "Ajoute {crops} : des légumineuses dont les nodules fixent environ {n} kg d'azote par hectare et par an.",
        "ev_ntable": "Azote fixé par culture (valeurs indicatives)",
        "ev_soc": "Carbone organique du sol {soc} g/kg ({level})",
        "low": "faible", "moderate": "moyen",
        "why_om_cover": "{crops} apportent beaucoup de matière végétale au sol",
        "why_om_deep": "{crops} s'enracinent profondément (1,5 m ou plus) et ouvrent des canaux pour que la pluie s'infiltre",
        "why_om_generic": "Plus de résidus et de racines retournent au sol",
        "why_intercrop": "Cultive {pairs} ensemble dans le même champ : la légumineuse apporte de l'azote et couvre le sol sans abandonner la culture principale.",
        "why_pushpull": "Push-pull : le desmodium entre les rangs de maïs repousse les foreurs et la chenille légionnaire et réduit le Striga.",
        "why_infil": "Racines profondes, matière organique et couverture pendant les orages aident la pluie à pénétrer au lieu de ruisseler.",
        "why_pest": "Change de famille de plantes ({new} familles au lieu de {old}) et casse le cycle des ravageurs et maladies.",
        "why_water": "Utilise mieux la pluie : {new} % de l'eau des cultures vient de la pluie (aujourd'hui {old} %) ; manque d'eau environ {mm} mm par an.",
        "ev_et0": "Besoin en eau = coefficient cultural FAO-56 × évapotranspiration de référence (Penman-Monteith)",
        "why_drought": "{crops} supportent bien les périodes sèches.",
        "why_income": "Ajoute des cultures qui se vendent mieux localement et répartit le revenu sur l'année.",
        "why_forage": "Produit plus d'aliments pour le bétail (légumineuses fourragères ou résidus).",
        "why_climate": "Les cultures sont placées pour que leurs stades sensibles évitent les mois les plus chauds et secs.",
        "ev_dry_months": "La pluie couvre moins de la moitié des besoins en eau en {months}",
        "ev_heat_months": "Jours fréquents au-dessus de 35 °C en {months}",
        "ev_gedi": "La végétation naturelle dans un rayon de {km} km contient environ {mean} t/ha de biomasse, un repère de ce que cette terre peut produire",
        "ev_esi": "Les plantes ont manqué d'eau en {months} (indice de stress ECOSTRESS inférieur à 0,6)",
        "ev_landsat": "À 30 m, le champ est le plus vert en {month}",
        "ev_events": "{n} événements naturels enregistrés à moins de {km} km ces {years} dernières années (dernier : {title})",
        "ev_soiltest": "Votre propre analyse de sol a remplacé les valeurs modélisées",
        "ev_lapse": "Températures corrigées de {shift} °C pour l'altitude du champ ({field} m contre {grid} m en moyenne sur la maille NASA)",
        "gap_norain": "La pluie seule ne suffit pas ici : chaque option suppose l'eau que vous avez indiquée.",
        "benefit_bare": "Mois de sol nu par an : {old} → {new}",
        "benefit_n": "Azote gratuit des légumineuses : environ {n} kg N/ha par an (moins d'engrais à acheter)",
        "benefit_water": "Manque d'eau : {old} → {new} mm par an",
        "benefit_fam": "Familles de plantes dans la rotation : {old} → {new}",
        "benefit_score": "{label} : {old} → {new} (sur 100)",
        "benefit_none": "Proche de votre rotation actuelle sur la plupart des critères, avec d'autres cultures.",
        "risk_lower": "{label} plus faible qu'aujourd'hui ({old} → {new}).",
        "risk_heat": "{when} : risque de stress thermique (environ {days} jours très chauds autour de la floraison).",
        "risk_water": "{when} : risque de manque d'eau (environ {mm} mm non couverts par la pluie ou le sol).",
        "risk_frost": "{when} : risque de gel ({days} nuits sous sa température critique).",
        "risk_waterlog": "{when} : risque d'engorgement les mois très humides ; demande un sol bien drainé.",
        "when": "{crop} semé en {month} (année {year})",
        "risk_new": "Nouveau pour cette ferme : {crops}. Vérifiez semences, savoir-faire et acheteurs avant de changer.",
        "risk_pests": "{crop} : surveiller {pests}.",
        "risk_perennial": "Un fourrage pérenne peut être difficile à enlever quand vous voulez recultiver le champ.",
        "risk_heat_trend": "Les jours très chauds augmentent ici ; les stades sensibles de {crops} pourraient devenir plus risqués.",
        "risk_onset_trend": "La saison des pluies commence de plus en plus tard ; les semis précoces devront peut-être être décalés.",
        "risk_weak_year": "Plus faible lors d'une « {name} » ({pct} % des années passées) : adaptation au climat {fit}/100.",
        "risk_no_market": "Vous avez indiqué qu'il n'y a pas d'acheteur près de chez vous pour {crops}.",
        "risk_irrigation": "Demande environ {mm} mm d'eau en plus par an, plus que l'eau dont vous disposez.",
        "robust_summary": "Tient bon dans {ok} types d'année sur {n}",
        "gap_demo": "DONNÉES DE DÉVELOPPEMENT : ces chiffres sont synthétiques. Pas pour de vraies décisions.",
        "gap_power": "La météo est une moyenne NASA POWER sur ~50 km ; votre champ peut être plus humide, sec, chaud ou frais.",
        "gap_smap": "L'humidité du sol SMAP est une moyenne sur 9 km et n'existe que depuis 2015.",
        "gap_nosmap": "Pas encore d'humidité du sol satellite : l'humidité modélisée (NASA POWER) est utilisée.",
        "gap_grace": "Le stockage d'eau GRACE couvre ~300 km ; il montre la tendance régionale, pas votre puits.",
        "gap_eco_pending": "ECOSTRESS (stress hydrique des plantes à 70 m) est encore en préparation à la NASA ; revenez plus tard.",
        "gap_traits": "Les caractéristiques des cultures et les prix sont des estimations générales, pas des prix ou variétés locales.",
        "gap_pests": "Ravageurs, maladies, main-d'œuvre et foncier ne sont pas dans les données.",
        "gap_soilmodel": "Les valeurs du sol sont modélisées (SoilGrids 250 m) ; une analyse de sol est bien plus fiable.",
        "ask_dates": "Confirmez les dates de semis et les variétés avec votre conseiller agricole.",
        "ask_seed": "Trouvez des semences et des acheteurs pour {crops}.",
        "ask_inoculant": "Demandez si les légumineuses ont besoin d'inoculum de rhizobium sur votre sol.",
        "ask_soiltest": "Faites une analyse de sol (pH, N, P, K, matière organique) pour confirmer les hypothèses.",
        "ask_market": "Vérifiez les prix actuels de {crops} au marché le plus proche.",
        "c_demo": "données de développement", "c_disagree": "les sources de pluie divergent",
        "c_agree": "deux sources de pluie indépendantes concordent", "c_short": "historique climatique court",
        "c_new_n": "{n} cultures nouvelles pour la ferme", "c_limit": "une culture est à la limite de son climat",
        "c_sensitive": "sensible à certains types d'année", "c_nondvi": "pas d'historique satellite de végétation",
        "c_soiltest": "votre analyse de sol a été utilisée", "c_eco": "le stress ECOSTRESS confirme les mois secs",
        "summary_current": "Votre rotation actuelle, notée avec les mêmes règles que les suggestions.",
        "summary": "{seq}. Plus grands gains : {gains}. Attention : {watch}",
        "summary_nothing": "rien de majeur signalé par les données",
        "balance": "un autre équilibre",
        "headline_rain": "Environ {mm} mm de pluie par an ; les cultures poussent sous pluie seule en {windows}.",
        "headline_none": "aucune saison fiable",
        "headline_changing": "Ce qui change : {items}.",
        "headline_bare": "Les satellites montrent le champ surtout nu en {months}.",
        "fallow": "Jachère", "year_short": "A",
    },
}


def lang_of(lang: str | None) -> str:
    return lang if lang in T else "en"


def t(lang: str, key: str, **kw) -> str:
    table = T.get(lang_of(lang), T["en"])
    text = table.get(key) or T["en"].get(key, key)
    try:
        out = text.format(**kw)
    except (KeyError, IndexError):
        out = text
    out = out.replace("..", ".")
    return out[:1].upper() + out[1:] if out else out


def months_text(lang: str, months: list[int]) -> str:
    names = MONTHS.get(lang_of(lang), MONTHS["en"])
    items = [names[m - 1] for m in sorted(months)]
    return join(lang, items)


def month_name(lang: str, m: int) -> str:
    return MONTHS.get(lang_of(lang), MONTHS["en"])[m - 1]


def join(lang: str, items: list[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {AND.get(lang_of(lang), 'and')} " + items[-1]


def criterion(lang: str, key: str) -> str:
    return CRITERIA.get(lang_of(lang), CRITERIA["en"]).get(key, key)


TREND = {
    "en": {"labels": {"tmax": "Daytime temperature", "heat_days": "Very hot days (>35°C)", "frost_days": "Frost nights",
                      "rain": "Yearly rainfall", "heavy_days": "Heavy-rain days", "onset_doy": "Start of the rains",
                      "ndvi": "Greenness (NDVI)", "smap_rootzone": "Soil moisture (SMAP)",
                      "grace_lwe": "Stored water (GRACE)"},
           "none": "{label}: no clear change", "up": "{label} rising by {v}{unit} per {per}",
           "down": "{label} falling by {v}{unit} per {per}",
           "later": "The rains start about {v} days later each decade",
           "earlier": "The rains start about {v} days earlier each decade",
           "decade": "decade", "year": "year"},
    "fr": {"labels": {"tmax": "Température de jour", "heat_days": "Jours très chauds (>35 °C)", "frost_days": "Nuits de gel",
                      "rain": "Pluie annuelle", "heavy_days": "Jours de forte pluie", "onset_doy": "Début des pluies",
                      "ndvi": "Verdure (NDVI)", "smap_rootzone": "Humidité du sol (SMAP)",
                      "grace_lwe": "Eau stockée (GRACE)"},
           "none": "{label} : pas de changement net", "up": "{label} en hausse de {v}{unit} par {per}",
           "down": "{label} en baisse de {v}{unit} par {per}",
           "later": "Les pluies commencent environ {v} jours plus tard chaque décennie",
           "earlier": "Les pluies commencent environ {v} jours plus tôt chaque décennie",
           "decade": "décennie", "year": "an"},
}


def trend_sentence(lang: str, card: dict) -> str:
    tt = TREND.get(lang_of(lang), TREND["en"])
    label = tt["labels"].get(card["key"], card["label"])
    slope = card["slope"]
    if not card["significant"]:
        return tt["none"].format(label=label)
    if card["key"] == "onset_doy":
        return tt["later" if slope > 0 else "earlier"].format(v=round(abs(slope)))
    unit = {"°C": " °C", "days": " j" if lang == "fr" else " days", "mm": " mm", "cm": " cm",
            "m³/m³": " m³/m³"}.get(card["unit"], "")
    v = f"{abs(slope):.2g}"
    if lang == "fr":
        v = v.replace(".", ",")
    return tt["up" if slope > 0 else "down"].format(label=label, v=v, unit=unit, per=tt[card["per"]])
