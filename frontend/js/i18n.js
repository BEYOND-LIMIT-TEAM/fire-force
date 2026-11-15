/* Textes de la page d'accueil et de la page About, en anglais et en français. Le dashboard reste en français. */
const KEY = "ff-lang";
let lang = "en";
try {
  const saved = localStorage.getItem(KEY);
  lang = saved === "fr" || saved === "en" ? saved : (navigator.language || "en").toLowerCase().startsWith("fr") ? "fr" : "en";
} catch (e) { /* stockage indisponible : on garde l'anglais */ }

export const STR = {
  en: {
    "nav.about": "About", "nav.home": "Home", "nav.lang": "Français",
    "hero.kicker": "NASA Space Apps Challenge 2026",
    "hero.sub": "GLOBAL FIRE INTELLIGENCE SYSTEM",
    "hero.tag": "Understanding Earth's fire activity through satellite intelligence.",
    "hero.line": "From space, we observe. Through data, we understand.",
    "hero.blurb": "An intelligent geospatial platform designed to analyze historical forest fire activity through harmonized MODIS and VIIRS satellite observations.",
    "btn.start": "ACCESS PLATFORM", "btn.about": "ABOUT", "btn.explore": "EXPLORE THE MISSION", "btn.skip": "Skip intro", "btn.back": "BACK TO HOME",
    "hot.cap": "Most active cells, last 12 months of data",
    "mis.title": "How the mission works",
    "mis.lead": "Four stages take raw satellite detections to a calendar you can read.",
    "mis.cta": "Open the platform",
    "about.title": "ABOUT FIRE FORCE",
    "about.sub": "Understanding forest fire activity through satellite intelligence.",
    "about.pTitle": "The challenge",
    "about.p": "Forest fires are a major environmental issue. Understanding them requires satellite data that lets us study their activity across time and space.",
    "about.sTitle": "Our solution",
    "about.s": "FIRE FORCE is a geospatial analysis platform that harmonizes observations from the MODIS and VIIRS sensors to make the historical study of fire activity easier.",
    "about.goalsTitle": "The platform aims to",
    "about.goals": ["Collect and use satellite observations.", "Harmonize data from several sensors.", "Analyze how activity evolves over time.", "Identify trends and seasonality.", "Spot historical periods of high activity.", "Show the results on an interactive map.", "Produce a calendar of activity periods."],
    "about.howTitle": "How it works",
    "about.note": "FIRE FORCE is a solution under development, proposed as part of the NASA Space Apps Challenge. Satellite hot spots are thermal detections, not certain proof of fires, and historical trends are not guaranteed predictions.",
    "pipe": [
      ["SATELLITE DATA", "Acquisition of MODIS and VIIRS observations."],
      ["DATA HARMONIZATION", "Cleaning, normalization and aggregation."],
      ["SCIENTIFIC ANALYSIS", "Statistics, trends and seasonality."],
      ["GEO INTELLIGENCE", "Mapping and activity calendar."],
    ],
    "team.title": "MEET THE TEAM",
    "team.line": "BEYOND LIMITE — A team driven by innovation, science and technology, committed to exploring new possibilities through data.",
    "team.slotName": "Name to add", "team.slotRole": "Role to add",
    "credits": "Fire detections: NASA FIRMS (MODIS, VIIRS). Land outlines: Natural Earth, via world-atlas.",
    "title.landing": "Fire Force — Global Fire Intelligence System", "title.about": "About — Fire Force",
  },
  fr: {
    "nav.about": "À propos", "nav.home": "Accueil", "nav.lang": "English",
    "hero.kicker": "NASA Space Apps Challenge 2026",
    "hero.sub": "SYSTÈME D'INTELLIGENCE MONDIALE DES FEUX",
    "hero.tag": "Comprendre l'activité des feux sur Terre grâce à l'intelligence satellitaire.",
    "hero.line": "De l'espace, nous observons. Par les données, nous comprenons.",
    "hero.blurb": "Une plateforme géospatiale intelligente conçue pour analyser l'activité historique des feux de forêt à partir d'observations satellitaires MODIS et VIIRS harmonisées.",
    "btn.start": "COMMENCER", "btn.about": "À PROPOS", "btn.explore": "EXPLORER LA MISSION", "btn.skip": "Passer l'intro", "btn.back": "RETOUR À L'ACCUEIL",
    "hot.cap": "Cellules les plus actives, 12 derniers mois de données",
    "mis.title": "Comment fonctionne la mission",
    "mis.lead": "Quatre étapes mènent des détections satellitaires brutes à un calendrier lisible.",
    "mis.cta": "Ouvrir la plateforme",
    "about.title": "À PROPOS DE FIRE FORCE",
    "about.sub": "Comprendre l'activité des feux de forêt grâce à l'intelligence satellitaire.",
    "about.pTitle": "Le défi",
    "about.p": "Les feux de forêt sont un enjeu environnemental majeur. Les comprendre exige des données satellitaires qui permettent d'étudier leur activité dans le temps et dans l'espace.",
    "about.sTitle": "Notre solution",
    "about.s": "FIRE FORCE est une plateforme d'analyse géospatiale qui harmonise les observations des capteurs MODIS et VIIRS pour faciliter l'étude historique de l'activité des feux.",
    "about.goalsTitle": "La plateforme vise à",
    "about.goals": ["Collecter et exploiter des observations satellitaires.", "Harmoniser les données de plusieurs capteurs.", "Analyser leur évolution dans le temps.", "Identifier les tendances et la saisonnalité.", "Repérer les périodes historiques de forte activité.", "Visualiser les résultats sur une carte interactive.", "Produire un calendrier des périodes d'activité."],
    "about.howTitle": "Fonctionnement",
    "about.note": "FIRE FORCE est une solution en cours de développement, proposée dans le cadre du NASA Space Apps Challenge. Les points chauds satellitaires sont des détections thermiques, pas des preuves certaines d'incendies, et les tendances historiques ne sont pas des prédictions garanties.",
    "pipe": [
      ["DONNÉES SATELLITAIRES", "Acquisition des observations MODIS et VIIRS."],
      ["HARMONISATION", "Nettoyage, normalisation et agrégation."],
      ["ANALYSE SCIENTIFIQUE", "Statistiques, tendances et saisonnalité."],
      ["GÉO-INTELLIGENCE", "Cartographie et calendrier d'activité."],
    ],
    "team.title": "L'ÉQUIPE",
    "team.line": "BEYOND LIMITE — Une équipe animée par l'innovation, la science et la technologie, engagée à explorer de nouvelles possibilités grâce aux données.",
    "team.slotName": "Nom à renseigner", "team.slotRole": "Rôle à renseigner",
    "credits": "Détections de feux : NASA FIRMS (MODIS, VIIRS). Contours des terres : Natural Earth, via world-atlas.",
    "title.landing": "Fire Force — Système d'intelligence mondiale des feux", "title.about": "À propos — Fire Force",
  },
};

export const getLang = () => lang;
export const t = (k) => STR[lang][k] ?? STR.en[k] ?? k;
export function setLang(l) {
  lang = l === "fr" ? "fr" : "en";
  try { localStorage.setItem(KEY, lang); } catch (e) { /* idem */ }
}
/** Applique les textes aux éléments [data-i18n] d'un conteneur. */
export function apply(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(el.dataset.i18n); });
}
