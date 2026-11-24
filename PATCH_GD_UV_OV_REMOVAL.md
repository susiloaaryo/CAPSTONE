# Historical note — superseded by NEWEST.ebc mapping

This file describes an older layout that expected FC02 and non-contiguous GD
status ranges. It is retained only as project history and is **not** the active
contract for the uploaded `NEWEST(1).ebc` project.

The active mapping is contiguous FC01:
- GI: FC01 coils 0..5 (CS0..5).
- GD: FC01 coils 0..9 (CS0..9).

Do not apply the old segmented FC02 instructions. See `EBC_CS_MAPPING.md` and
`HUE_DIRECT_POLLING_GUIDE.md` for the active mapping and reset limitations.
