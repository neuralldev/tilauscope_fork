# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.

# AUTHOR
# Tilau 2025-2026

"""The flavour wheel, shared by both apps: families, groups, subgroups and notes,
each with its colour. A coffee's flavour notes are the chosen notes in lower
case, sorted, comma separated (notes_text)."""

FLAVOR_WHEEL_DATA = {
    "Enzymatic": {
        "color": "#8B3A2B",
        "groups": {
            "Fruits": {
                "color": "#D35400",
                "subgroups": {
                    "Citric": {"color": "#E67E22", "notes": ["Orange", "Blood orange", "Orange peel", "Tangerine", "Grapefruit", "Yuzu", "Bergamot", "Lemon", "Green Lemon", "Lemon peel", "Lime", "Physalis"]},
                    "Stone fruits": {"color": "#C0392B", "notes": ["Peach", "Yellow peach", "Nispero", "Apricot", "Black plum", "Yellow plum", "Red plum", "Red cherry", "Black cherry", "Nectarine"]},
                    "Berries": {"color": "#922B21", "notes": ["Strawberry", "Blueberry", "Raspberry", "Redcurrant", "Blackcurrant", "Blackberry", "Red mulberry", "Red grape", "White grape"]},
                    "Yellow fruits": {"color": "#F4D03F", "notes": ["Apple", "Red Apple", "Green Apple", "Golden Apple", "Pomegranate", "Pear", "Coffee cherry", "Blueberry raisins", "Grape raisin"]},
                    "Other fruits": {"color": "#D2B4DE", "notes": ["Raisins", "Prunes", "Dried Peaches", "Dried apple", "Dehydrated pear", "Dehydrated strawberry"]},
                    "Tropical fruits": {"color": "#F39C12", "notes": ["Pineapple", "Banana", "Semi-Ripe Banana", "Passion Fruit", "Mango", "Papaya", "Kiwi", "Melon", "Watermelon", "Coconut", "Guava", "Tamarind", "Starfruit", "Lychee", "Persimmon"]}
                }
            },
            "Fragrances": {
                "color": "#F9E79F",
                "subgroups": {
                    "Floral": {"color": "#FEF9E7", "notes": ["Hibiscus", "Camellia", "Azalea", "Lilly", "Dark rose", "Rose", "Jasmine", "White flower"]},
                    "Herbal": {"color": "#D4EFDF", "notes": ["Chamomile", "Violet", "Rhubarb", "Black Tea", "Green Tea"]}
                }
            },
            "Alcohols": {
                "color": "#FADBD8",
                "subgroups": {
                    "Winey": {"color": "#FDEDEC", "notes": ["White wine", "Rosé wine", "Red wine", "Champagne", "Porto"]},
                    "Liqueurs": {"color": "#F5EEF8", "notes": ["Whisky", "Rum", "Anise liqueur", "Almond liqueur"]}
                }
            },
            "Fermentation": {
                "color": "#D5DBDB",
                "subgroups": {
                    "Acetic": {"color": "#E5E8E8", "notes": ["Yogurt", "Over ripe fruit"]},
                    "Lactic": {"color": "#F2F3F4", "notes": ["Yogurt"]}
                }
            }
        }
    },
    "Caramelization": {
        "color": "#2B4C8B",
        "groups": {
            "Sweets": {
                "color": "#2E86C1",
                "subgroups": {
                    "Sugars": {"color": "#AED6F1", "notes": ["Cane sugar", "Muscovado sugar", "Panela", "Molasses", "Maple Syrup", "Honey", "Dulce de leche"]},
                    "Caramels": {"color": "#3498DB", "notes": ["Light brown caramel", "Dark brown caramel", "Toffee"]}
                }
            },
            "Chocolates": {
                "color": "#4A235A",
                "subgroups": {
                    "Chocolaty": {"color": "#5B2C6F", "notes": ["Butter", "Vanilla", "White chocolate", "Milk chocolate", "Dark chocolate", "Cocoa"]}
                }
            },
            "Nutty": {
                "color": "#5499C7",
                "subgroups": {
                    "Nutty": {"color": "#85C1E9", "notes": ["Marzipan", "Hazelnut", "Roasted almond", "Almond", "Peanuts", "Walnut", "Macadamia"]}
                }
            },
            "Cereals": {
                "color": "#A9CCE3",
                "subgroups": {
                    "Cereals": {"color": "#D4E6F1", "notes": ["Malt", "Wheat", "Toasted bread", "Oat", "Biscuit"]}
                }
            }
        }
    },
    "Dry distillation": {
        "color": "#1E4D2B",
        "groups": {
            "Spices": {
                "color": "#7D6608",
                "subgroups": {
                    "Spicy": {"color": "#9A7D0A", "notes": ["Pepper", "Ginger", "Nutmeg", "Cinnamon", "Anise", "Clove"]},
                    "Woody": {"color": "#1D8348", "notes": ["Cedar", "Tobacco", "Pipe tobacco"]}
                }
            },
            "Vegetables": {
                "color": "#145A32",
                "subgroups": {
                    "Vegetables": {"color": "#1E8449", "notes": ["Cucumber", "Tomato", "Pumpkin", "Carrot", "Olive oil", "Peas", "Mushroom"]},
                    "Aromatic herbs": {"color": "#A9DFBF", "notes": ["Basil", "Mint", "Lemon grass", "Fennel", "Thyme", "Rosemary", "Bay leaf"]}
                }
            }
        }
    }
}


def notes_text(notes: set[str]) -> str:
    """The flavour notes text of a set of notes, as the record keeps it."""
    return ", ".join(sorted(notes))
