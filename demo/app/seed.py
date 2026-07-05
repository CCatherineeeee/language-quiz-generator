"""Seed a small reference taxonomy spanning A1 -> B2. These are 'reference' concepts
(informational), NOT things the user knows. The user's own 'known' concepts come from
the intake flow. Idempotent. Run:  python -m demo.app.seed   (or via run.sh)"""
from . import db

# (code, name, kind, level)
SEED_CONCEPTS = [
    ("grammar:etre_avoir_present", "être / avoir (present tense)", "grammar", "A1"),
    ("grammar:present_er_verbs", "Present tense, -er verbs", "grammar", "A1"),
    ("grammar:articles_definis", "Definite/indefinite articles", "grammar", "A1"),
    ("grammar:passe_compose", "Passé composé", "grammar", "A2"),
    ("grammar:imparfait", "Imparfait", "grammar", "A2"),
    ("grammar:futur_simple", "Futur simple", "grammar", "B1"),
    ("grammar:subjonctif_present", "Subjonctif présent", "grammar", "B2"),
    ("grammar:connecteurs_logiques", "Logical connectors", "grammar", "B2"),
    ("vocab:salutations", "Greetings & introductions", "vocab", "A1"),
    ("vocab:nombres", "Numbers", "vocab", "A1"),
    ("vocab:famille", "Family & people", "vocab", "A1"),
    ("vocab:quotidien", "Daily life & routines", "vocab", "A2"),
    ("comprehension:idee_principale", "Main idea", "comprehension", "B1"),
    ("comprehension:inference", "Inference", "comprehension", "B2"),
]


def run():
    db.init_db()
    for code, name, kind, level in SEED_CONCEPTS:
        db.execute(
            """INSERT INTO demo_concepts (code, name, kind, level, status)
               VALUES (%s, %s, %s, %s, 'reference')
               ON CONFLICT (code) DO UPDATE SET status = 'reference'""",
            (code, name, kind, level),
        )
    n = db.query_one(
        "SELECT count(*) AS c FROM demo_concepts WHERE status = 'reference'")["c"]
    print(f"Seed done. {n} reference concepts available.")


if __name__ == "__main__":
    run()
