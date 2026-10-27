# GREYBOX — Human × AI
# Ren'Py entry point. Story content is loaded from JSON by story_adapter.rpy.

label start:
    scene black
    with fade

    centered "GREYBOX"
    centered "任せる。検証する。決断する。"

    $ greybox_run_story()

    centered "STAGE 01 COMPLETE"
    return
