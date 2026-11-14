import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import app as manager


class ModManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "SimCity 2013"
        (self.root / "SimCityData").mkdir(parents=True)
        (self.root / "SimCityData" / "SimCity_Game.package").write_bytes(b"DBPFfake-game-base")
        self.state_file = Path(self.temp.name) / "state.json"
        self.state_file.write_text(json.dumps({"managed": {}, "history": []}), encoding="utf-8")
        patcher_root = patch.object(manager, "game_root", return_value=self.root)
        patcher_state = patch.object(manager, "STATE_FILE", self.state_file)
        patcher_root.start()
        patcher_state.start()
        self.addCleanup(patcher_root.stop)
        self.addCleanup(patcher_state.stop)

    def test_game_found(self):
        self.assertTrue(manager.valid_game(self.root))

    def test_no_simcity4(self):
        base = Path(self.temp.name) / "SimCity 4 Deluxe"
        (base / "SimCityData").mkdir(parents=True)
        (base / "SimCityData" / "SimCity_Game.package").write_bytes(b"DBPFtest")
        self.assertFalse(manager.valid_game(base))

    def test_package_archive(self):
        p = Path(self.temp.name) / "mod.zip"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("folder/000_offline_akar.package", b"DBPFtestfile")
            z.writestr("README.txt", b"read")
            z.writestr("../bad.package", b"DBPFno")
        found = manager.packages_from_file(p)
        self.assertEqual(found, [("000_offline_akar.package", b"DBPFtestfile")])

    def test_reject_bad_data(self):
        p = Path(self.temp.name) / "fake.package"
        p.write_bytes(b"not a real package")
        with self.assertRaises(ValueError):
            manager.packages_from_file(p)

    def test_reject_original_package(self):
        with self.assertRaises(ValueError):
            manager.validate_package("SimCity_Game.package", b"DBPFtest")

    def test_install_scan_remove(self):
        mod = manager.CAT_BY_ID["akar"]
        result = manager.install_packages(mod, [("000_offline_akar.package", b"DBPFtestdata")])
        self.assertEqual(result["installed"], 1)
        file = self.root / "SimCityData" / "000_offline_akar.package"
        self.assertTrue(file.exists())
        inventory, mods = manager.scan(self.root)
        self.assertEqual(len(inventory), 2)
        self.assertTrue(next(m for m in mods if m["id"] == "akar")["installed"])
        self.assertTrue(next(m for m in mods if m["id"] == "akar")["managed"])
        self.assertEqual(manager.delete_managed("akar")["removed"], 1)
        self.assertFalse(file.exists())

    def test_cannot_replace_existing(self):
        mod = manager.CAT_BY_ID["akar"]
        (self.root / "SimCityData" / "000_akar.package").write_bytes(b"DBPFmanual")
        with self.assertRaisesRegex(ValueError, "já existe"):
            manager.install_packages(mod, [("000_akar.package", b"DBPFtestdata")])


if __name__ == "__main__":
    unittest.main()
