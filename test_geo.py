import re
import json

def test_extract(title):
    clean_title = re.split(r'\s-\s|\s\|\s', title)[0]
    out = {
        "original": title,
        "cleaned": clean_title,
        "regex": None,
        "fallback": None
    }
    
    m_loc = re.search(r"(?<!Authority\s)(?<!Government\s)(?<!Ministry\s)(?<!Bank\s)(?:in|near|of|strikes|hits|at|off|for)\s([A-Z][A-Za-z]+(?:\s[A-Z][A-Za-z]+)*)", clean_title)
    if m_loc:
        out["regex"] = m_loc.group(1)
        
    text = clean_title.lower()
    
    if "iran" in text or "tehran" in text: 
        out["fallback"] = "Iran"
    elif "india" in text or "kashmir" in text or "manipur" in text:
        out["fallback"] = "India"
    elif "middle east" in text:
        out["fallback"] = "Middle East"
    elif "sri lanka" in text:
        out["fallback"] = "Sri Lanka"
    else:
        out["fallback"] = "None"
    
    return out

res = [
    test_extract("Iran Earthquake Sparks Nuclear Test Speculations Amid War; ‘US Monitoring Closely’ - The Times of India Magnitude: 4.0 *Sources: 1*"),
    test_extract("[SUSPECTED] 208 Middle East Flights Cancelled Over Safety Concerns says Civil Aviation Authority of Sri Lanka - Newsfirst")
]
print(json.dumps(res, indent=2))
