init -100 python in gui:

    def scale(n):
        return int(n)

init 100 python in gui:

    if not renpy.mobile:
        from store import config

        import sys
        import os
        sys.path.insert(0, os.path.join(config.renpy_base, "launcher", "game"))

        from gui7.parameters import GuiParameters
        from gui7.images import ImageGenerator
        from gui7 import generate_gui

        p = GuiParameters(
            config.gamedir, config.gamedir,
            config.screen_width, config.screen_height,
            accent_color, "#000000", False, None,
            True, False, False, "gui")

        p.skip_backup = True

        # 配布ビルドで launcher/game が存在しない場合のフォールバック
        import os as _os
        icon_path = _os.path.join(config.renpy_base, "launcher", "game", "gui7", "icon.png")
        if not _os.path.isfile(icon_path):
            icon_path = _os.path.join(config.gamedir, "gui7", "icon.png")
            # generate_icon が launcher/game を参照するため、シンボリックリンク的に配置
            launcher_dir = _os.path.join(config.renpy_base, "launcher", "game")
            if not _os.path.isdir(launcher_dir):
                _os.makedirs(launcher_dir, exist_ok=True)
            gui7_dir = _os.path.join(launcher_dir, "gui7")
            if not _os.path.isdir(gui7_dir):
                _os.makedirs(gui7_dir, exist_ok=True)
            # icon.png のみコピー（他のファイルは不要）
            import shutil
            shutil.copy2(icon_path, _os.path.join(gui7_dir, "icon.png"))

        generate_gui(p)

        _skip_backup = True
        _gui_images()
