"""
Topic Mapper for English Dataset System Engine.

Maps raw Kaikki topic keys (e.g. "computing") to a curated,
learner-friendly theme taxonomy. Falls back to a normalized raw title
for topics not present in the map.
"""

from typing import Dict

THEME_MAP: Dict[str, str] = {
    # Technology
    "computing": "Technology",
    "software": "Technology",
    "internet": "Technology",
    "electronics": "Technology",
    "computer": "Technology",
    "programming": "Technology",
    "telecommunications": "Technology",
    "networking": "Technology",
    "artificial intelligence": "Technology",
    # Health & Medicine
    "medicine": "Health & Medicine",
    "medical": "Health & Medicine",
    "anatomy": "Health & Medicine",
    "pharmacology": "Health & Medicine",
    "pharmacy": "Health & Medicine",
    "nutrition": "Health & Medicine",
    "psychiatry": "Health & Medicine",
    "psychology": "Health & Medicine",
    "diseases": "Health & Medicine",
    # Business & Finance
    "money": "Business & Finance",
    "finance": "Business & Finance",
    "business": "Business & Finance",
    "economics": "Business & Finance",
    "economy": "Business & Finance",
    "commerce": "Business & Finance",
    "accounting": "Business & Finance",
    "taxation": "Business & Finance",
    "marketing": "Business & Finance",
    # Law & Government
    "law": "Law & Government",
    "legal": "Law & Government",
    "government": "Law & Government",
    "politics": "Law & Government",
    "military": "Law & Government",
    "crime": "Law & Government",
    "police": "Law & Government",
    # Travel & Transportation
    "travel": "Travel & Transportation",
    "tourism": "Travel & Transportation",
    "shipping": "Travel & Transportation",
    "aeronautics": "Travel & Transportation",
    "aviation": "Travel & Transportation",
    "rail transport": "Travel & Transportation",
    "automotive": "Travel & Transportation",
    "nautical": "Travel & Transportation",
    # Food & Drink
    "food": "Food & Drink",
    "cooking": "Food & Drink",
    "cuisine": "Food & Drink",
    "culinary": "Food & Drink",
    "gastronomy": "Food & Drink",
    "beverages": "Food & Drink",
    "alcoholic beverages": "Food & Drink",
    # Education & Language
    "education": "Education & Language",
    "linguistics": "Education & Language",
    "grammar": "Education & Language",
    "phonetics": "Education & Language",
    "phonology": "Education & Language",
    # Arts & Entertainment
    "art": "Arts & Entertainment",
    "arts": "Arts & Entertainment",
    "music": "Arts & Entertainment",
    "film": "Arts & Entertainment",
    "fiction": "Arts & Entertainment",
    "literature": "Arts & Entertainment",
    "literary": "Arts & Entertainment",
    "theatre": "Arts & Entertainment",
    "dance": "Arts & Entertainment",
    "photography": "Arts & Entertainment",
    "painting": "Arts & Entertainment",
    "gaming": "Arts & Entertainment",
    # Nature & Animals
    "zoology": "Nature & Animals",
    "botany": "Nature & Animals",
    "ornithology": "Nature & Animals",
    "entomology": "Nature & Animals",
    "ichthyology": "Nature & Animals",
    "mammals": "Nature & Animals",
    "ecology": "Nature & Animals",
    "agriculture": "Nature & Animals",
    # Science & Mathematics
    "mathematics": "Science & Mathematics",
    "math": "Science & Mathematics",
    "physics": "Science & Mathematics",
    "chemistry": "Science & Mathematics",
    "biology": "Science & Mathematics",
    "astronomy": "Science & Mathematics",
    "geology": "Science & Mathematics",
    # Sports & Fitness
    "sports": "Sports & Fitness",
    "athletics": "Sports & Fitness",
    "boxing": "Sports & Fitness",
    "football": "Sports & Fitness",
    "soccer": "Sports & Fitness",
    "cricket": "Sports & Fitness",
    "tennis": "Sports & Fitness",
    "golf": "Sports & Fitness",
    # Communication & Media
    "media": "Communication & Media",
    "journalism": "Communication & Media",
    "press": "Communication & Media",
    "publishing": "Communication & Media",
    "advertising": "Communication & Media",
    # Religion, Spirituality & Culture
    "religion": "Religion & Culture",
    "religious": "Religion & Culture",
    "christianity": "Religion & Culture",
    "islam": "Religion & Culture",
    "buddhism": "Religion & Culture",
    "hinduism": "Religion & Culture",
    "judaism": "Religion & Culture",
    "mythology": "Religion & Culture",
    "culture": "Religion & Culture",
    "history": "Religion & Culture",
    "archaeology": "Religion & Culture",
    # Home & Family
    "family": "Home & Family",
    "furniture": "Home & Family",
    "household": "Home & Family",
    "textiles": "Home & Family",
    # Emotions & Personality
    "emotions": "Emotions & Personality",
    "personality": "Emotions & Personality",
    # Fashion & Clothing
    "clothing": "Fashion & Clothing",
    "fashion": "Fashion & Clothing",
    # Geography & Environment
    "geography": "Geography & Environment",
    "environment": "Geography & Environment",
    # Weather
    "weather": "Weather & Climate",
    "climate": "Weather & Climate",
    "meteorology": "Weather & Climate",
}


class TopicMapper:
    """Maps raw Kaikki topic keys to curated themes."""

    @staticmethod
    def map_topic(raw: str) -> str:
        key = raw.strip().lower()
        theme = THEME_MAP.get(key)
        if theme:
            return theme
        return key.replace("-", " ").title()
