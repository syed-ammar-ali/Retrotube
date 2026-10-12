"""Curated Hall of Fame viral milestones for Time Machine eras (2006-2016)."""
from typing import Dict, List

# Definitive cultural landmarks and viral sensations for each year
ERA_MILESTONES: Dict[int, List[str]] = {
    2006: [
        "dMH0bHeiRNg",  # Evolution of Dance - Judson Laipply
        "dTAAsCNK7RA",  # OK Go - Here It Goes Again (Treadmills)
        "QjA5faZF1A8",  # funtwo - Canon Rock
        "vr3x_RRJdd4",  # Free Hugs Campaign
        "EAcdvmnZ_GM",  # The Sneezing Baby Panda
        "LjbJELjLgZg",  # Diet Coke + Mentos Experiment
        "qgyG2i6Xj_I",  # Ask A Ninja - Episode 1
        "gx-NLPH8JeM",  # Little Superstar
    ],
    2007: [
        "_OBlgSz8sSM",  # Charlie bit my finger - again !
        "EwTZ2xpQwpA",  # Tay Zonday - Chocolate Rain
        "WqSTXuJeTks",  # Leave Britney Alone! - Chris Crocker
        "a1Y73sPHKxw",  # Dramatic Look / Dramatic Chipmunk
        "Tx1XIm6q4r4",  # Potter Puppet Pals: The Mysterious Ticking Noise
        "8UFIYGkROII",  # Soulja Boy Tell'em - Crank That
        "dQw4w9WgXcQ",  # Rick Astley - Never Gonna Give You Up (The Rickroll)
        "k80Uo_R_yV4",  # The Landlord - Will Ferrell / Funny Or Die
    ],
    2008: [
        "PQHPYelqr08",  # Weezer - Pork and Beans (YouTube Meme Compilation)
        "wQ2_Lg2b2g4",  # Fred Goes Swimming
        "cvCjyWp398A",  # Christian the Lion Reunion
        "w9u034tL-Z0",  # Super Mario Bros - Frustration
        "BsnwN9b-9s8",  # Where the Hell is Matt? 2008
        "eDMgpNkW3Gk",  # The Last Lecture - Randy Pausch
    ],
    2009: [
        "txqiwrbYGrs",  # David After Dentist
        "J---aiyznGQ",  # Charlie Schmidt's Keyboard Cat! - THE ORIGINAL
        "RxPZh4AnWyk",  # Susan Boyle - Britain's Got Talent 2009
        "W45DRy7M1no",  # Boom Goes The Dynamite
        "4-94JhLEiN0",  # JK Wedding Entrance Dance
    ],
    2010: [
        "hMtZfW2z9dw",  # Bed Intruder Song - Antoine Dodson
        "OQSNhk5ICTI",  # Yosemitebear Mountain Giant Double Rainbow
        "owGykVbfgUE",  # Old Spice - The Man Your Man Could Smell Like
        "_JmA2ClUvUY",  # Talking Twin Babies
    ],
    2011: [
        "kfVsfOSbJY0",  # Rebecca Black - Friday
        "QH2-TGUlwu4",  # Nyan Cat [original]
        "ZZ5LpwO-An4",  # HE-MAN HEYYEAYEA
    ],
    2012: [
        "9bZkp7q19f0",  # PSY - GANGNAM STYLE
        "sTSA_sWGM44",  # Dumb Ways to Die
        "BaW_jenozKc",  # Prancercise: A Fitness Revolution
        "xwtbHHGQo2o",  # Carly Rae Jepsen - Call Me Maybe
    ],
    2013: [
        "jofNR_WkoCE",  # Ylvis - The Fox (What Does The Fox Say?)
        "4TX7_2T3m48",  # Harlem Shake (original army edition)
    ],
    2014: [
        "D-UmfqFjpl0",  # Bill Gates ALS Ice Bucket Challenge
        "nfWlot6h_JM",  # Taylor Swift - Shake It Off
    ],
    2015: [
        "ZXsQAXx_ao0",  # Shia LaBeouf "Just Do It" Motivational Speech
        "NuWyD3F-bMU",  # Viral Edit
    ],
    2016: [
        "072tU1tamd0",  # PPAP (Pen Pineapple Apple Pen)
    ],
}


def get_milestone_ids(year: int) -> List[str]:
    """Return the curated list of milestone video IDs for a given year."""
    return ERA_MILESTONES.get(year, [])


def get_all_milestone_ids() -> List[str]:
    """Return all milestone video IDs across all eras."""
    all_ids: List[str] = []
    for y_ids in ERA_MILESTONES.values():
        all_ids.extend(y_ids)
    return all_ids

