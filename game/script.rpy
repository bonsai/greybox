# GREYBOX — Human × AI
# Ren'Py entry point. Story content is loaded from JSON by story_adapter.rpy.

define config.name = "GREYBOX"
define config.version = "0.1.0"
define gui.show_name = True

label start:
    scene black
    with fade

    centered "GREYBOX"
    centered "任せる。検証する。決断する。"

    $ greybox_run_story()

    centered "STAGE 01 COMPLETE"
    return
