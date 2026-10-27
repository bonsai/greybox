# GREYBOX JSON story adapter for Ren'Py.
# Runtime story data lives in game/story/stage01.json (generated from story/stage01.json).
# Keep story content in JSON; this file contains only execution behavior.

init -10 python:
    import json

    def greybox_load_story():
        with renpy.open_file("story/stage01.json") as story_file:
            story = json.load(story_file)

        scene_ids = [scene["id"] for scene in story["scenes"]]
        if len(scene_ids) != len(set(scene_ids)):
            raise Exception("GREYBOX story error: duplicate scene id")

        scene_map = {scene["id"]: scene for scene in story["scenes"]}
        if story["start_scene"] not in scene_map:
            raise Exception("GREYBOX story error: start_scene does not exist")

        characters = story.get("characters", {})
        events = story.get("events", {})
        choice_ids = []

        for scene in story["scenes"]:
            targets = []
            if scene["type"] in ("dialogue", "event"):
                targets.append(scene["next"])
            elif scene["type"] == "choice":
                targets.extend(choice["next"] for choice in scene["choices"])
                choice_ids.extend(choice["id"] for choice in scene["choices"])

            for target in targets:
                if target not in scene_map:
                    raise Exception(
                        "GREYBOX story error: scene '%s' points to missing scene '%s'"
                        % (scene["id"], target)
                    )

            if scene["type"] == "dialogue" and scene["speaker"] not in characters:
                raise Exception(
                    "GREYBOX story error: scene '%s' uses unknown speaker '%s'"
                    % (scene["id"], scene["speaker"])
                )

            if scene["type"] == "event" and scene["event"] not in events:
                raise Exception(
                    "GREYBOX story error: scene '%s' uses unknown event '%s'"
                    % (scene["id"], scene["event"])
                )

        if len(choice_ids) != len(set(choice_ids)):
            raise Exception("GREYBOX story error: duplicate choice id")

        return story, scene_map

    def greybox_apply_effects(state, effects):
        for key, value in effects.items():
            if isinstance(value, bool):
                state[key] = value
            elif isinstance(value, (int, float)) and isinstance(state.get(key), (int, float)) and not isinstance(state.get(key), bool):
                state[key] += value
            else:
                state[key] = value

    def greybox_run_story():
        story, scene_map = greybox_load_story()
        events = story.get("events", {})
        state = dict(story.get("initial_state", {}))
        characters = story.get("characters", {})
        speakers = {}
        current_id = story["start_scene"]

        while current_id:
            scene = scene_map[current_id]
            scene_type = scene["type"]

            if scene_type == "dialogue":
                speaker_id = scene["speaker"]
                if speaker_id not in speakers:
                    speakers[speaker_id] = Character(characters[speaker_id]["name"])
                renpy.say(speakers[speaker_id], scene["text"])
                current_id = scene["next"]

            elif scene_type == "event":
                # Event names index data-only effects. JSON never contains code.
                greybox_apply_effects(state, events[scene["event"]])
                current_id = scene["next"]

            elif scene_type == "choice":
                renpy.say(None, scene["text"])
                options = [(choice["text"], choice["id"]) for choice in scene["choices"]]
                selected_id = renpy.display_menu(options)
                selected = next(choice for choice in scene["choices"] if choice["id"] == selected_id)
                greybox_apply_effects(state, selected.get("effects", {}))
                current_id = selected["next"]

            elif scene_type == "ending":
                renpy.say(None, scene["title"] + "\n\n" + scene["text"])
                renpy.say(None, "結果: %s | 時間: %s | 品質: %s | リスク: %s" % (
                    scene["outcome"],
                    state.get("time", "-"),
                    state.get("quality", "-"),
                    state.get("risk", "-")
                ))
                current_id = None

            else:
                raise Exception("GREYBOX story error: unsupported scene type '%s'" % scene_type)

        return state
