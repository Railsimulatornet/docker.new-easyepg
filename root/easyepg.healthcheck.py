#!/usr/bin/env python3
"""Read the existing local status API without starting a grab or contacting providers."""
import http.client
import json
import math
import sys


def validate_status(data):
    if not isinstance(data, dict) or data.get('success') is not True:
        raise ValueError('Die lokale Statusabfrage war nicht erfolgreich.')
    result = data.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('grabbing'), bool):
        raise ValueError('Der Abrufzustand fehlt.')
    if not isinstance(result.get('status'), str) or not result['status'].strip():
        raise ValueError('Die Zustandsbeschreibung fehlt.')
    progress = result.get('progress')
    if isinstance(progress, bool) or not isinstance(progress, (int, float)) or not math.isfinite(progress):
        raise ValueError('Die Fortschrittsangabe ist ungültig.')
    return True


def check_health(host='127.0.0.1', port=4000, timeout=3):
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request('GET', '/api/grabber-status', headers={'Connection': 'close'})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Der lokale Statusdienst antwortet nicht erfolgreich.')
        body = response.read(16385)
        if len(body) > 16384:
            raise ValueError('Die lokale Statusantwort ist zu groß.')
        return validate_status(json.loads(body))
    finally:
        connection.close()


def main():
    try:
        check_health()
    except (OSError, ValueError, http.client.HTTPException):
        print('Die lokale EasyEPG-Betriebsprüfung ist fehlgeschlagen.', file=sys.stderr)
        return 1
    print('Die EasyEPG-Anwendung liefert einen gültigen Betriebszustand.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
