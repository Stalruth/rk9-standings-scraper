from datetime import datetime, timezone
import json
import re
import argparse
import os

from bs4 import BeautifulSoup
import unicodedata
import requests

from player import Player
from event import Event


def remove_country(name):
    start = name.find(' [')
    stop = name.find(']')
    if stop - start == 4:
        return name[0:start]
    return name


# removing accents (for js calls)
def strip_accents(input_str):
    nfkd_form = unicodedata.normalize('NFKD', input_str)
    only_ascii = nfkd_form.encode('ASCII', 'ignore')
    return only_ascii


# points access for sorting function
def points(elem):
    return elem.points


def get_round_count(players):
    if 4 <= players <= 8:
        return 3, 0, 0
    elif players <= 12:
        return 4, 0, 2
    elif players <= 20:
        return 5, 0, 2
    elif players <= 32:
        return 5, 0, 3
    elif players <= 64:
        return 6, 0, 3
    elif players <= 128:
        return 7, 0, 3
    elif players <= 226:
        return 8, 0, 3
    elif players <= 799:
        return 9, 5, 3
    else:
        return 9, 6, 3


def parse_rk9_date_range(input_str):
    months = {
        'jan': '01',
        'feb': '02',
        'mar': '03',
        'apr': '04',
        'may': '05',
        'jun': '06',
        'jul': '07',
        'aug': '08',
        'sep': '09',
        'oct': '10',
        'nov': '11',
        'dec': '12'
    }
    date_fields = input_str.replace('–', ' ').replace('-', ' ').replace(', ', ' ').split(" ")
    if len(date_fields) > 4:
        start_date = f'{date_fields[4]}-{months[date_fields[0].strip()[:3].lower()]}-{int(date_fields[1]):02d}'
        end_date = f'{date_fields[4]}-{months[date_fields[2].strip()[:3].lower()]}-{int(date_fields[3]):02d}'
    else:
        start_date = f'{date_fields[3]}-{months[date_fields[0].strip()[:3].lower()]}-{int(date_fields[1]):02d}'
        end_date = f'{date_fields[3]}-{months[date_fields[0].strip()[:3].lower()]}-{int(date_fields[2]):02d}'
    return start_date, end_date


def main_worker(directory, link, output_dir):
    last_page_loaded = ""

    url = 'https://rk9.gg/tournament/' + link
    page = requests.get(url)
    soup = BeautifulSoup(page.content, "lxml")

    page_title = soup.find('h3', {'class': 'mb-0'}).text
    title = page_title.split('\n')[0]
    date = page_title.split('\n')[1]
    dates = parse_rk9_date_range(date)

    rounds = []
    now = datetime.now()
    str_time = now.strftime("%Y/%m/%d - %H:%M:%S")
    print('starting at : ' + str_time)

    tour_data = Event(directory, title, dates[0], dates[1], link)

    for division_name in tour_data.divisions:
        division = tour_data.divisions[division_name]
        standing = division.standing
        print(f'{tour_data.event_id}/{division_name}')

        standing_directory = f'{output_dir}/{tour_data.event_id}/{division_name}'
        os.makedirs(standing_directory, exist_ok=True)
        os.makedirs(f'{standing_directory}/players', exist_ok=True)

        teams = None
        try:
            with open(f"{standing_directory}/teams.json", 'r') as teams_file:
                teams = json.load(teams_file)
        except FileNotFoundError:
            # File is added by team scraping process (currently Flintstoned)
            pass

        winner = None
        # requesting RK9 pairings webpage
        url = 'https://rk9.gg/pairings/' + tour_data.rk9_id
        print("\t" + url)
        if last_page_loaded != url:
            last_page_loaded = url
            page = requests.get(url)
            # page content to BeautifulSoup
            soup = BeautifulSoup(page.content, "lxml")

        # finding out how many rounds on the page
        rounds_from_url = 0
        for ultag in soup.find_all('ul', {'class': 'nav nav-pills'}):
            for litag in ultag.find_all('li'):
                for aria in litag.find_all('a'):
                    sp = aria.text.split(" ")
                    if sp[0][0:-1].lower() == division_name[0:len(sp[0][0:-1])]:
                        rounds_from_url = int(sp[len(sp) - 1])
                        standing.level = str(aria['aria-controls'])

        are_rounds_set = False
        standing.current_round = rounds_from_url

        rounds_data = soup.find_all("div", id=lambda value: value and value.startswith(standing.level + "R"))

        rounds.append(rounds_from_url)

        # scrapping standings if available, to compare results later
        standing_published_data = soup.find('div', attrs={'id': standing.level + "-standings"})
        published_standings = []
        if standing_published_data:
            standing_published = [y for y in [x.strip() for x in standing_published_data.text.split('\n')] if y]
            for line in standing_published:
                data = line.split(' ')
                player = ''
                for i in range(1, len(data)):
                    if i > 1:
                        player += ' '
                    player += data[i]
                published_standings.append(player.replace('  ', ' '))

        for iRounds in range(rounds_from_url):
            players_dictionary = {}
            for player in standing.players:
                counter = 0
                while f"{player.name}#{counter}" in players_dictionary:
                    counter += 1
                players_dictionary[f"{player.name}#{counter}"] = player

            tables = []
            round_data = rounds_data[iRounds]
            matches = round_data.find_all('div', attrs={'class': 'match'})
            still_playing = 0
            for match_data in matches:
                player1_name = ""
                player2_name = ""
                p1status = -1
                p2status = -1
                p1dropped = False
                p2dropped = False
                p1late = 0
                p2late = 0
                scores1 = []
                scores2 = []
                p1 = None
                p2 = None
                table = "0"

                table_data = match_data.find('div', attrs={'class': 'col-2'})
                if table_data:
                    table_data = table_data.find('span', attrs={'class': 'tablenumber'})
                    if table_data:
                        table = table_data.text

                player_data = match_data.find('div', attrs={'class': 'player1'})
                text_data = player_data.text.split('\n')
                name = player_data.find('span', attrs={'class': 'name'})
                if name:
                    score = text_data[3].strip().replace('(', '').replace(')', '')
                    scores1 = list(map(int, re.split('-', score)))
                    player1_name = re.sub(r'\s+', ' ', name.text)
                    pdata_text = str(player_data)
                    if pdata_text.find(" winner") != -1:
                        p1status = 2
                    elif pdata_text.find(" loser") != -1:
                        p1status = 0
                    elif pdata_text.find(" tie") != -1:
                        p1status = 1
                    if pdata_text.find(" dropped") != -1:
                        p1dropped = True
                    if p1status == -1 and not p1dropped:
                        if iRounds + 1 < rounds_from_url:
                            p1status = 0
                            if iRounds == 0:
                                p1late = -1

                player_data = match_data.find('div', attrs={'class': 'player2'})
                text_data = player_data.text.split('\n')
                name = player_data.find('span', attrs={'class': 'name'})
                if name:
                    score = text_data[3].strip().replace('(', '').replace(')', '')
                    scores2 = list(map(int, re.split('-', score)))
                    player2_name = re.sub(r'\s+', ' ', name.text)
                    pdata_text = str(player_data)
                    if pdata_text.find(" winner") != -1:
                        p2status = 2
                    elif pdata_text.find(" loser") != -1:
                        p2status = 0
                    elif pdata_text.find(" tie") != -1:
                        p2status = 1
                    if pdata_text.find(" dropped") != -1:
                        p2dropped = True
                    if p2status == -1 and not p2dropped:
                        if iRounds + 1 < rounds_from_url:
                            p2status = 0
                            if iRounds == 0:
                                p2late = -1

                result = []
                counter = 0
                while player1_name + '#' + str(counter) in players_dictionary:
                    result.append(players_dictionary[player1_name + '#' + str(counter)])
                    counter += 1

                if len(result) > 0:
                    for player in result:
                        if p1status == -1 and (
                                player.wins == scores1[0] and player.losses == scores1[1] and player.ties ==
                                scores1[2]):
                            p1 = player
                            still_playing += 1
                        elif p1status == 0 and (
                                player.wins == scores1[0] and player.losses + 1 == scores1[1] and player.ties ==
                                scores1[2]):
                            p1 = player
                        elif p1status == 1 and (
                                player.wins == scores1[0] and player.losses == scores1[1] and player.ties + 1 ==
                                scores1[2]):
                            p1 = player
                        elif p1status == 2 and (
                                player.wins + 1 == scores1[0] and player.losses == scores1[1] and player.ties ==
                                scores1[2]):
                            p1 = player

                        if p1dropped:
                            if p1 is None:
                                if player.wins == scores1[0] and player.losses == scores1[1] and player.ties == \
                                        scores1[2]:
                                    p1 = player
                            else:
                                p1.dropRound = iRounds + 1
                        if p1:
                            break

                result = []
                counter = 0
                while player2_name + '#' + str(counter) in players_dictionary:
                    result.append(players_dictionary[player2_name + '#' + str(counter)])
                    counter += 1

                if len(result) > 0:
                    for player in result:
                        if p2status == -1 and (
                                player.wins == scores2[0] and player.losses == scores2[1] and player.ties ==
                                scores2[2]):
                            p2 = player
                            still_playing += 1
                        elif p2status == 0 and (
                                player.wins == scores2[0] and player.losses + 1 == scores2[1] and player.ties ==
                                scores2[2]):
                            p2 = player
                        elif p2status == 1 and (
                                player.wins == scores2[0] and player.losses == scores2[1] and player.ties + 1 ==
                                scores2[2]):
                            p2 = player
                        elif p2status == 2 and (
                                player.wins + 1 == scores2[0] and player.losses == scores2[1] and player.ties ==
                                scores2[2]):
                            p2 = player

                        if p2dropped:
                            if p2 is None:
                                if player.wins == scores2[0] and player.losses == scores2[1] and player.ties == \
                                        scores2[2]:
                                    p2 = player
                            else:
                                p2.dropRound = iRounds + 1
                        if p2:
                            break

                if p1 is None:
                    if len(player1_name) > 0:
                        standing.player_id = standing.player_id + 1
                        p1 = Player(player1_name, division_name, standing.player_id, p1late)
                        if p1.name in standing.dqed or (
                                len(published_standings) > 0 and p1.name not in published_standings):
                            p1.dqed = True
                        standing.players.append(p1)

                if p2 is None:
                    if len(player2_name) > 0:
                        standing.player_id = standing.player_id + 1
                        p2 = Player(player2_name, division_name, standing.player_id, p2late)
                        if p2.name in standing.dqed or (
                                len(published_standings) > 0 and p2.name not in published_standings):
                            p2.dqed = True
                        standing.players.append(p2)

                if p1:
                    p1.add_match(p2, p1status, p1dropped, iRounds + 1 > standing.rounds_day1,
                                 iRounds + 1 > standing.rounds_day2, table)
                if p2:
                    p2.add_match(p1, p2status, p2dropped, iRounds + 1 > standing.rounds_day1,
                                 iRounds + 1 > standing.rounds_day2, table)

                if p1 is not None and p2 is not None:
                    tables.append({
                        'table': int(table),
                        'players': [
                            {
                                'name': p1.name,
                                'result': {-1: None, 0: 'L', 1: 'T', 2: 'W'}[p1status],
                                'record': {
                                    'wins': p1.wins,
                                    'losses': p1.losses,
                                    'ties': p1.ties
                                }
                            },
                            {
                                'name': p2.name,
                                'result': {-1: None, 0: 'L', 1: 'T', 2: 'W'}[p2status],
                                'record': {
                                    'wins': p2.wins,
                                    'losses': p2.losses,
                                    'ties': p2.ties
                                }
                            }
                        ]
                    })

            standing.tables.append({'tables': tables})

            if len(standing.hidden) > 0:
                for player in standing.players:
                    if player.name in standing.hidden:
                        standing.players.remove(player)

            nb_players = len(standing.players)

            for player in standing.players:
                if (len(player.matches) >= standing.rounds_day1) or standing.rounds_day1 > iRounds + 1:
                    player.update_win_percentage(standing.rounds_day1, standing.rounds_day2, iRounds + 1)
            for player in standing.players:
                if (len(player.matches) >= standing.rounds_day1) or standing.rounds_day1 > iRounds + 1:
                    player.update_opponent_win_percentage(standing.rounds_day1, standing.rounds_day2, iRounds + 1)
            for player in standing.players:
                if (len(player.matches) >= standing.rounds_day1) or standing.rounds_day1 > iRounds + 1:
                    player.update_oppopp_win_percentage(standing.rounds_day1, standing.rounds_day2, iRounds + 1)

            if iRounds + 1 <= standing.rounds_day2:
                standing.players.sort(key=lambda p: (
                    not p.dqed, p.points, p.late, round(p.opp_win_percentage * 100, 2),
                    round(p.oppopp_win_percentage * 100, 2)), reverse=True)
                placement = 1
                for player in standing.players:
                    if not player.dqed:
                        player.top_placement = placement
                        placement = placement + 1
                    else:
                        player.top_placement = 9999
            else:
                if iRounds + 1 > standing.rounds_day2:
                    for place in range(nb_players):
                        if len(standing.players[place].matches) == iRounds + 1:
                            if standing.players[place].matches[
                                    len(standing.players[place].matches) - 1].status == 2:  # if top win
                                stop = False
                                for above in range(place - 1, -1, -1):
                                    if not stop:
                                        if len(standing.players[place].matches) == len(
                                                standing.players[above].matches):
                                            if standing.players[above].matches[len(standing.players[
                                                    place].matches) - 1].status == 2:
                                                # if player above won, stop searching
                                                stop = True
                                            if standing.players[above].matches[len(standing.players[
                                                    place].matches) - 1].status == 0:
                                                # if player above won, stop searching
                                                temp_placement = standing.players[above].top_placement
                                                standing.players[above].top_placement = standing.players[
                                                    place].top_placement
                                                standing.players[place].top_placement = temp_placement
                                                standing.players.sort(key=lambda p: (
                                                    not p.dqed, nb_players - p.top_placement - 1, p.points, p.late,
                                                    round(p.opp_win_percentage * 100, 2),
                                                    round(p.oppopp_win_percentage * 100, 2)), reverse=True)
                                                place = place - 1

            # Late players are not considered when determining round count.
            # TODO: unless they are :^)
            nb_players_start = nb_players - len([entry for entry in filter(lambda p: getattr(p.matches[0].player, 'name', None) == "LATE", standing.players)])

            if are_rounds_set is False:
                are_rounds_set = True
                round_counts = get_round_count(nb_players_start)
                standing.rounds_day1 = round_counts[0]
                standing.rounds_day2 = round_counts[0] + round_counts[1]
                standing.rounds_cut = round_counts[2]

            if are_rounds_set is True and iRounds == 0:
                print(f'{len(standing.players)}/{standing.rounds_day1}/{standing.rounds_day2}')
                with open(f"{standing_directory}/players.json",
                          'w') as jsonPlayers:
                    json.dump({
                        'players': [{'id': str(player.id), 'name': player.name} for player in standing.players]
                    }, jsonPlayers, separators=(',', ':'), ensure_ascii=False)

            if iRounds + 1 == standing.rounds_day2 + standing.rounds_cut and still_playing == 0:
                winner = standing.players[0]

        with open(f"{standing_directory}/tables.json", 'w') as tables_file:
            json.dump(standing.tables, tables_file, separators=(',', ':'), ensure_ascii=False)

        if len(standing.players) > 0:
            tour_data.tournament_status = "running"
            tour_data.divisions[division_name].round_number = rounds_from_url
            tour_data.divisions[division_name].player_count = len(standing.players)
            if winner is not None:
                tour_data.divisions[division_name].winner = winner.name

        tour_data.add_to_index(f"{output_dir}/tournaments.json")

        with open(f"{standing_directory}/tables.csv", 'wb') as csvExport:
            for player in standing.players:
                if player:
                    player.to_csv(csvExport)

        with open(f"{standing_directory}/standings.json", 'w') as json_export:
            json.dump(standing.players, json_export, default=lambda o: o.summary_json(teams), separators=(',', ':'),
                      ensure_ascii=False)

        for player in standing.players:
            with open(f'{standing_directory}/players/{player.id}.json', 'w') as json_export:
                json.dump(player, json_export, default=lambda o: o.to_json(standing.players, teams), separators=(',', ':'), ensure_ascii=False)

        with open(f"{standing_directory}/discrepancy.txt", 'w') as discrepancy_report:
            if len(published_standings) > 0:
                for player in standing.players:
                    if player and player.top_placement - 1 < len(published_standings) and player.name != \
                            published_standings[player.top_placement - 1]:
                        discrepancy_report.write(
                            f"{player.top_placement} RK9: {published_standings[player.top_placement - 1]} --- {player.name}\n")

    tour_data.last_updated = datetime.now(timezone.utc).isoformat()

    winners = {
        'juniors': tour_data.divisions['juniors'].winner,
        'seniors': tour_data.divisions['seniors'].winner,
        'masters': tour_data.divisions['masters'].winner,
    }
    if winners['juniors'] is not None and winners['seniors'] is not None and winners['masters'] is not None:
        tour_data.tournament_status = "finished"

    with open(f"{output_dir}/{tour_data.event_id}/tournament.json", "w") as tournament_export:
        json.dump(tour_data.to_dict(), tournament_export, separators=(',', ':'), ensure_ascii=False)

    now = datetime.now()  # current date and time
    print('Ending at ' + now.strftime("%Y/%m/%d - %H:%M:%S") + " with no issues")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url")
    parser.add_argument("--id")
    parser.add_argument("--output-dir", help="output directory", default='.')

    args = parser.parse_args()

    """exemple: (Barcelona)
    id = '0000090'
    url = 'BA189xznzDvlCdfoQlBC'
    """
    os.makedirs(args.output_dir, exist_ok=True)
    main_worker(args.id, args.url, args.output_dir)
