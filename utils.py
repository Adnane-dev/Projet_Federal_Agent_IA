"""Plomberie du projet fédérateur : accès à la base, lecture des brochures, encodeur, affichages.

Rien ici n'est un exercice. Ce fichier existe pour que le notebook reste concentré sur
l'agent lui-même. Vous pouvez le lire, il n'y a aucune magie.

Les sections « Données », « Brochures », « Encodeur » et « Affichages » reprennent la
plomberie du Projet 07 du Cahier de vacances Machine Learnia. Les sections « Quiz »,
« Sérialisation » et « Client simulé » ont été ajoutées pour le projet fédérateur.
"""

import hashlib
import json
import os
import re
import sqlite3
from types import SimpleNamespace

import pandas as pd

DOSSIER = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(DOSSIER, "data", "voyages.db")
BROCHURES = os.path.join(DOSSIER, "data", "hotels")

ENCODEUR_PAR_DEFAUT = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


# --------------------------------------------------------------------------------------
# La base de données
# --------------------------------------------------------------------------------------

def connexion():
    """Ouvre la base de données des voyages (vols, activités, réservations).

    Retourne :
    conn -- une connexion sqlite3 ouverte
    """
    return sqlite3.connect(BASE)


def requete(conn, sql, params=()):
    """Exécute une requête SQL et retourne le résultat en DataFrame.

    Arguments :
    conn -- une connexion sqlite3 ouverte
    sql -- la requête SQL, avec des ? à la place des valeurs
    params -- le tuple des valeurs qui rempliront les ?

    Retourne :
    resultat -- un DataFrame des lignes renvoyées par la base
    """
    return pd.read_sql_query(sql, conn, params=params)


# --------------------------------------------------------------------------------------
# Les brochures d'hôtels (les PDF)
# --------------------------------------------------------------------------------------

def charger_brochures(dossier=BROCHURES):
    """Lit chaque brochure PDF et retourne une ligne par hôtel.

    Quelques informations sont écrites dans un format fixe à l'intérieur de chaque
    brochure (la ville, les étoiles, le prix, la note des voyageurs) : de simples
    expressions régulières les extraient. Tout le reste demeure du texte brut, car c'est
    lui que le modèle d'embeddings lira, et parce que "calme", "en famille" ou
    "romantique" ne sont écrits dans aucune colonne.

    Arguments :
    dossier -- le dossier contenant les brochures PDF

    Retourne :
    brochures -- un DataFrame avec les colonnes ville, hotel, etoiles, note, avis,
                 prix_nuit, texte (le document complet) et resume (la présentation
                 et les avis clients seulement)
    """
    from pypdf import PdfReader

    lignes = []
    for nom_fichier in sorted(os.listdir(dossier)):
        if not nom_fichier.endswith(".pdf"):
            continue
        lecteur = PdfReader(os.path.join(dossier, nom_fichier))
        texte = "\n".join((page.extract_text() or "") for page in lecteur.pages)
        entete = re.search(r"^(.+?) - (\d) etoiles - a partir de (\d+) euros la nuit", texte, re.M)
        note = re.search(r"Note des voyageurs : ([\d.]+) sur 10 \((\d+) avis\)", texte)
        plat = " ".join(texte.split())
        presentation = re.search(r"Presentation (.*?) Equipements", plat)
        avis_clients = re.search(r"Avis des clients (.*?) [A-ZÀ-Ý][^ ]* .*Brochure du reseau", plat)
        lignes.append({
            "ville": entete.group(1).strip() if entete else "?",
            "hotel": texte.strip().splitlines()[0].strip(),
            "etoiles": int(entete.group(2)) if entete else 0,
            "note": float(note.group(1)) if note else float("nan"),
            "avis": int(note.group(2)) if note else 0,
            "prix_nuit": float(entete.group(3)) if entete else float("nan"),
            "texte": plat,
            # Le "résumé" ne garde que la présentation et les avis clients : c'est là qu'on
            # trouve "calme", "en famille", "romantique". La liste d'équipements et le pied
            # de page sont quasi identiques d'une brochure à l'autre : les encoder ne ferait
            # qu'ajouter du bruit et rapprocher tous les hôtels les uns des autres.
            "resume": " ".join(x.group(1) for x in (presentation, avis_clients) if x) or plat,
        })
    return pd.DataFrame(lignes)


# --------------------------------------------------------------------------------------
# L'encodeur (les embeddings)
# --------------------------------------------------------------------------------------

def charger_encodeur(modele=ENCODEUR_PAR_DEFAUT):
    """Charge le modèle d'embeddings qui rapprochera une envie des brochures.

    Arguments :
    modele -- l'identifiant du modèle sur Hugging Face

    Retourne :
    encodeur -- un SentenceTransformer
    """
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(modele)


def encoder(encodeur, textes):
    """Transforme une liste de textes en vecteurs normalisés, prêts pour une similarité cosinus.

    Normalisés veut dire que chaque vecteur est de longueur 1 : la similarité cosinus
    entre deux d'entre eux se réduit alors à leur simple produit scalaire.

    Arguments :
    encodeur -- le modèle retourné par charger_encodeur
    textes -- une liste de textes

    Retourne :
    vecteurs -- un tableau de forme (nombre de textes, dimension)
    """
    return encodeur.encode(list(textes), normalize_embeddings=True)


# --------------------------------------------------------------------------------------
# Affichages
# --------------------------------------------------------------------------------------

def afficher_vols(vols, n=5):
    """Affiche proprement les vols les moins chers trouvés."""
    if vols.empty:
        print("  aucun vol")
        return
    for _, v in vols.head(n).iterrows():
        print(f"  {v['numero']:8s} {v['origine']:10s} -> {v['heure_depart']}  "
              f"{v['duree_h']:.1f} h  {v['prix_eur']:6.0f} EUR  ({v['places_restantes']:.0f} places)")


def afficher_hotels(hotels):
    """Affiche proprement les hôtels retournés par la recherche sémantique, avec leur score."""
    for _, h in hotels.iterrows():
        print(f"  {h['score']:.3f}  {h['hotel']:22s} {h['etoiles']}*  {h['prix_nuit']:5.0f} EUR/nuit  "
              f"note {h['note']:.1f}/10 ({h['avis']} avis)")
        print(f"          {h['resume'][:145]}...")


def afficher_voyage(voyage, journal=None):
    """Affiche un voyage complet, et ce que l'agent a dû sacrifier pour tenir le budget.

    Arguments :
    voyage -- le dictionnaire retourné par l'agent
    journal -- la liste, facultative, des ajustements de l'agent
    """
    if voyage is None:
        print("Aucun voyage ne rentre dans ce budget.")
        if journal:
            print("\nCe que l'agent a tenté :")
            for ligne in journal:
                print(f"  - {ligne}")
        return

    print(f"=== {voyage['destination']}, {voyage['nuits']} nuits, "
          f"{voyage['voyageurs']} voyageur(s) ===")
    print(f"  Vol    {voyage['vol']['numero']} au départ de {voyage['vol']['origine']} "
          f"le {voyage['date_depart']} à {voyage['vol']['heure_depart']}   "
          f"{voyage['vol']['prix_eur']:.0f} EUR/pers")
    print(f"  Hôtel  {voyage['hotel']['hotel']}, {voyage['hotel']['prix_nuit']:.0f} EUR/nuit : "
          f"{voyage['hotel']['prix_nuit'] * voyage['nuits']:.0f} EUR")
    if voyage["activites"]:
        print("  Activités :")
        for a in voyage["activites"]:
            print(f"      {a['nom']:38s} {a['prix_eur']:5.0f} EUR")
    else:
        print("  Activités : aucune")
    print(f"  {'-' * 52}")
    print(f"  TOTAL  {voyage['prix_total']:.0f} EUR   (budget : {voyage['budget_max']:.0f} EUR)")

    if journal:
        print("\nCe que l'agent a fait, et ce qu'il a remarqué :")
        for ligne in journal:
            print(f"  - {ligne}")


def texte_proposition(voyage, journal=None):
    """Rédige la proposition de voyage en un court paragraphe, sans aucun modèle de langage.

    Tout ce qui est écrit ici vient des chiffres calculés par l'agent : rien ne peut
    être inventé.

    Arguments :
    voyage -- le dictionnaire retourné par l'agent
    journal -- la liste, facultative, des ajustements de l'agent

    Retourne :
    texte -- la proposition, sous forme de texte
    """
    if voyage is None:
        return "Je n'ai rien trouvé qui rentre dans ce budget. Essayez d'augmenter le budget " \
               "ou de partir un autre jour : le prix des vols change beaucoup d'un jour à l'autre."

    v, h = voyage["vol"], voyage["hotel"]
    phrases = [
        f"Départ de {v['origine']} le {voyage['date_depart']} à {v['heure_depart']}, "
        f"{v['duree_h']:.0f} h de vol pour {v['prix_eur']:.0f} euros.",
        f"Vous dormez {voyage['nuits']} nuits au {h['hotel']}, à {h['prix_nuit']:.0f} euros la nuit.",
    ]
    if voyage["activites"]:
        noms = ", ".join(a["nom"] for a in voyage["activites"])
        phrases.append(f"Au programme : {noms}.")
    phrases.append(f"Le tout revient à {voyage['prix_total']:.0f} euros par personne, "
                   f"pour un budget de {voyage['budget_max']:.0f}.")
    # Le journal contient deux sortes de lignes : les sacrifices consentis pour tenir le
    # budget, et les remarques de l'agent sur ce qu'il a repéré ailleurs. On les rédige
    # différemment, sinon la phrase devient incompréhensible.
    remarque = ("au passage", "en revanche")
    sacrifices = [l for l in journal or [] if not l.startswith(remarque)]
    remarques = [l for l in journal or [] if l.startswith(remarque)]

    if sacrifices:
        phrases.append("Pour y arriver, " + " puis ".join(sacrifices).lower() + ".")
    for ligne in remarques:
        phrases.append(ligne[0].upper() + ligne[1:] + ".")
    return " ".join(phrases)


# --------------------------------------------------------------------------------------
# Quiz du Module 0
# --------------------------------------------------------------------------------------

# Les réponses attendues ne sont stockées que sous forme d'empreintes (hachage SHA-256),
# pour que la lecture de ce fichier ne vous donne pas la solution par accident. Ce n'est
# pas un coffre-fort : avec cinq étiquettes possibles, on pourrait tout essayer. Le but
# de l'exercice est de réfléchir, pas de gagner.
_EMPREINTES_QUIZ = {
    "thermostat": "1c415a1160b191d4",
    "aspirateur": "c0d5252051d5d5a0",
    "gps_chemin": "474e8bb951476d2b",
    "gps_compromis": "763df5ff9e372e43",
    "antispam": "6fc0ad6da15d3a10",
}


def verifier_quiz(reponses):
    """Corrige le quiz de typologie des agents.

    Arguments :
    reponses -- un dictionnaire {système: étiquette}

    Retourne :
    erreurs -- la liste des systèmes mal classés (vide si tout est juste)
    """
    erreurs = []
    for systeme, empreinte in _EMPREINTES_QUIZ.items():
        reponse = str(reponses.get(systeme, "")).strip().lower()
        if hashlib.sha256(f"{systeme}|{reponse}".encode()).hexdigest()[:16] != empreinte:
            erreurs.append(systeme)
    return erreurs


# --------------------------------------------------------------------------------------
# Sérialisation des résultats d'outils (Modules 4 et 10)
# --------------------------------------------------------------------------------------

def en_json(objet):
    """Transforme le résultat d'un outil en texte JSON, c'est-à-dire ce qu'un LLM lira.

    Les nombres numpy (comme les scores de similarité) et les objets pandas ne sont pas
    sérialisables tels quels : ils sont convertis au passage.

    Arguments :
    objet -- un dictionnaire, une liste, un nombre...

    Retourne :
    texte -- la représentation JSON de l'objet, accents conservés
    """
    def convertir(o):
        if isinstance(o, (pd.Series, pd.DataFrame)):
            return o.to_dict()
        if hasattr(o, "item"):            # nombres numpy : float32, int64...
            return o.item()
        return str(o)

    return json.dumps(objet, ensure_ascii=False, default=convertir)


# --------------------------------------------------------------------------------------
# Le client simulé (Module 10)
# --------------------------------------------------------------------------------------

class ClientSimule:
    """Un faux client Claude, pour tester la boucle d'un agent LLM sans clé d'API ni réseau.

    Il rejoue un scénario écrit à l'avance. Chaque étape du scénario est soit une liste
    d'appels d'outils [(nom, arguments), ...], que le « modèle » demande en même temps,
    soit un texte, qui est la réponse finale du « modèle ».

    À chaque appel, il VÉRIFIE que votre boucle lui a renvoyé la conversation au bon
    format, exactement comme le ferait la vraie API, qui refuse un message mal formé.
    Il s'utilise comme un vrai client : client.beta.messages.create(...).

    Attributs utiles pour les tests :
    nb_appels -- le nombre d'appels reçus
    erreurs_signalees -- le drapeau is_error de chaque tool_result reçu, dans l'ordre
    resultats_recus -- le contenu (texte JSON) de chaque tool_result reçu, dans l'ordre
    """

    def __init__(self, scenario):
        self.scenario = list(scenario)
        self.nb_appels = 0
        self.erreurs_signalees = []
        self.resultats_recus = []
        self._derniere_reponse = None
        self._ids_attendus = []
        self.messages = SimpleNamespace(create=self._repondre)
        self.beta = SimpleNamespace(messages=self.messages)

    def _verifier(self, messages, tools):
        assert isinstance(messages, list) and messages, "messages doit être une liste non vide"
        assert messages[0].get("role") == "user", "Le premier message doit venir de l'utilisateur"
        assert tools, "Le client n'a reçu aucun outil : passez tools=... à create()"
        if self._derniere_reponse is None:
            return

        attendu = 1 + 2 * self.nb_appels
        assert len(messages) == attendu, (
            f"Au tour {self.nb_appels + 1}, la conversation devrait contenir {attendu} messages, "
            f"elle en contient {len(messages)}. À chaque tour, il faut ajouter la réponse de "
            f"l'assistant, PUIS un seul message utilisateur avec tous les résultats.")

        assistant, utilisateur = messages[-2], messages[-1]
        assert isinstance(assistant, dict) and assistant.get("role") == "assistant" and \
            assistant.get("content") == self._derniere_reponse.content, (
            "(1) L'avant-dernier message doit être {'role': 'assistant', 'content': reponse.content}, "
            "avec le contenu de la réponse tel quel")
        assert isinstance(utilisateur, dict) and utilisateur.get("role") == "user" and \
            isinstance(utilisateur.get("content"), list), (
            "(3) Le dernier message doit être {'role': 'user', 'content': resultats}, "
            "avec la liste des résultats du tour")

        blocs = utilisateur["content"]
        for b in blocs:
            assert isinstance(b, dict) and b.get("type") == "tool_result", \
                "(2) Chaque résultat doit être un dictionnaire de type 'tool_result'"
            assert isinstance(b.get("content"), str), \
                "(2) Le content d'un tool_result doit être un texte : utilisez en_json(resultat)"
            assert isinstance(b.get("is_error"), bool), \
                "(2) Indiquez is_error (True ou False) dans chaque tool_result"
        ids = [b.get("tool_use_id") for b in blocs]
        assert sorted(ids) == sorted(self._ids_attendus), (
            "(2) Les tool_use_id ne correspondent pas aux demandes du modèle : chaque résultat doit "
            "reprendre bloc.id, et tous les résultats d'un même tour doivent être dans le même message")

        self.erreurs_signalees += [b["is_error"] for b in blocs]
        self.resultats_recus += [b["content"] for b in blocs]

    def _repondre(self, *, messages, tools=None, **_autres_parametres):
        self._verifier(messages, tools)
        if self.nb_appels < len(self.scenario):
            etape = self.scenario[self.nb_appels]
        else:
            etape = "(fin du scénario simulé)"
        self.nb_appels += 1

        if isinstance(etape, str):
            contenu = [SimpleNamespace(type="text", text=etape)]
            reponse = SimpleNamespace(stop_reason="end_turn", content=contenu)
        else:
            contenu = [SimpleNamespace(type="text", text="Je consulte mes outils.")]
            for i, (nom, arguments) in enumerate(etape):
                contenu.append(SimpleNamespace(type="tool_use", id=f"toolu_simule_{self.nb_appels}_{i}",
                                               name=nom, input=arguments))
            reponse = SimpleNamespace(stop_reason="tool_use", content=contenu)

        self._ids_attendus = [b.id for b in contenu if b.type == "tool_use"]
        self._derniere_reponse = reponse
        return reponse
