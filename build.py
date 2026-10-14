"""Generate the rule indexes during a Vercel build, without provider calls."""
from fsae_search.store import build

if __name__ == '__main__':
    corpus = build()
    print(f"Built {corpus['numbered_nodes']} numbered entries and {corpus['search_units']} search units.")
