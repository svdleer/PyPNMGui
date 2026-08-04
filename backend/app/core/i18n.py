DEFAULT_LOCALE = "en-US"
SUPPORTED_LOCALES = {
    "en-US": "English (US)",
    "nl-NL": "Nederlands (NL)",
}


TRANSLATIONS = {
    "en-US": {
        "nav.home": "Home",
        "nav.modems": "Modems",
        "nav.measurements": "Measurements",
        "nav.fiber_node": "Fiber Node",
        "nav.topology": "Topology",
        "nav.account": "Account",
        "nav.change_password": "Change Password",
        "nav.admin": "Admin",
        "nav.logout": "Logout",
        "language.label": "Language",
        "language.saved": "Language preference updated",
        "language.invalid": "Unsupported language",
        "badges.file": "File",
        "search.title": "Cable Modem Search",
        "search.search_by": "Search By",
        "search.search_value": "Search Value",
        "search.search": "Search",
        "search.ip": "IP Address",
        "search.mac": "MAC Address",
        "search.name": "Name",
        "search.cmts_filter": "CMTS Filter",
        "search.all_cmts": "All CMTS",
        "search.interface_filter": "Interface Filter",
        "search.all_interfaces": "All Interfaces",
        "search.cmts_search": "CMTS Search",
        "search.search_hostname": "Search by hostname...",
        "search.get_modems": "Get Modems",
        "search.loading": "Loading...",
        "search.enriching": "Enriching...",
        "search.clear_cache": "Clear Cache",
        "search.enrich_modems": "Enrich modems (model, firmware, cable-mac)",
        "search.no_cm_agent": "no CM agent",
        "search.back": "Back",
        "account.title": "Account",
        "account.identity": "Account Identity",
        "account.change_password": "Change Password",
        "account.current_password": "Current Password",
        "account.new_password": "New Password",
        "account.confirm_password": "Confirm Password",
        "account.update_password": "Update Password",
        "account.preferences": "Preferences",
        "account.save_preferences": "Save Preferences",
        "placeholder.ip": "e.g., 192.168.100.10",
        "placeholder.mac": "aa:bb:cc:dd:ee:01 · aabb.ccdd.ee01 · aabbccddee01",
        "placeholder.name": "e.g., CM-Residential",
        "placeholder.search_value": "Enter search value",
    },
    "nl-NL": {
        "nav.home": "Start",
        "nav.modems": "Modems",
        "nav.measurements": "Metingen",
        "nav.fiber_node": "Fiberknoop",
        "nav.topology": "Topologie",
        "nav.account": "Account",
        "nav.change_password": "Wachtwoord wijzigen",
        "nav.admin": "Beheer",
        "nav.logout": "Uitloggen",
        "language.label": "Taal",
        "language.saved": "Taalvoorkeur opgeslagen",
        "language.invalid": "Niet-ondersteunde taal",
        "badges.file": "Bestand",
        "search.title": "Kabelmodem zoeken",
        "search.search_by": "Zoeken op",
        "search.search_value": "Zoekwaarde",
        "search.search": "Zoeken",
        "search.ip": "IP-adres",
        "search.mac": "MAC-adres",
        "search.name": "Naam",
        "search.cmts_filter": "CMTS-filter",
        "search.all_cmts": "Alle CMTS",
        "search.interface_filter": "Interface-filter",
        "search.all_interfaces": "Alle interfaces",
        "search.cmts_search": "CMTS zoeken",
        "search.search_hostname": "Zoek op hostnaam...",
        "search.get_modems": "Modems ophalen",
        "search.loading": "Laden...",
        "search.enriching": "Verrijken...",
        "search.clear_cache": "Cache wissen",
        "search.enrich_modems": "Modems verrijken (model, firmware, cable-mac)",
        "search.no_cm_agent": "geen CM-agent",
        "search.back": "Terug",
        "account.title": "Account",
        "account.identity": "Accountgegevens",
        "account.change_password": "Wachtwoord wijzigen",
        "account.current_password": "Huidig wachtwoord",
        "account.new_password": "Nieuw wachtwoord",
        "account.confirm_password": "Bevestig wachtwoord",
        "account.update_password": "Wachtwoord opslaan",
        "account.preferences": "Voorkeuren",
        "account.save_preferences": "Voorkeuren opslaan",
        "placeholder.ip": "bv. 192.168.100.10",
        "placeholder.mac": "aa:bb:cc:dd:ee:01 · aabb.ccdd.ee01 · aabbccddee01",
        "placeholder.name": "bv. CM-Residential",
        "placeholder.search_value": "Voer een zoekwaarde in",
    },
}


def normalize_locale(value):
    text = str(value or "").strip()
    if text in SUPPORTED_LOCALES:
        return text
    lowered = text.lower()
    for locale in SUPPORTED_LOCALES:
        if locale.lower() == lowered:
            return locale
    return DEFAULT_LOCALE


def get_messages(locale):
    normalized = normalize_locale(locale)
    return TRANSLATIONS.get(normalized, TRANSLATIONS[DEFAULT_LOCALE])


def translate(locale, key, default=None):
    messages = get_messages(locale)
    if key in messages:
        return messages[key]
    return default if default is not None else TRANSLATIONS[DEFAULT_LOCALE].get(key, key)