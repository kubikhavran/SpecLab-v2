SpecLab – Spectrum Visualization and Analysis Tool

1. Overview

SpecLab is a desktop application for practical spectrum visualization and analysis in laboratory workflows. It helps you load, inspect, and compare one or multiple spectra in a single view, including overlay mode for direct comparison. The app includes peak detection and manual peak labeling/editing to support fast interpretation of spectral features. It is also designed for quick figure and data export for reports, presentations, and publication preparation.

-------------------------------------------------------

2. Installation (Windows)

1. Run the installer file:
   SpecLab_x.x.x_x64-setup.exe
2. Follow the installation wizard.
3. Launch SpecLab from the Start Menu.

If Windows SmartScreen appears:
- Click "More info"
- Click "Run anyway"

SpecLab installs locally on your machine. In standard use, installation is per user and typically does not require administrator privileges.

-------------------------------------------------------

3. Quick Start Guide

1) Load spectrum data in the Data section.
2) Display multiple spectra together (overlay mode) for comparison.
3) Adjust processing as needed (Cosmic rays, Baseline, Smoothing).
4) Detect peaks automatically from the Peaks section.
5) Add peaks manually by clicking on the plot.
6) Remove peaks using Shift + click on a peak label, or click a label and press Backspace/Delete.
7) Adjust axis labels and graphic styling in the Graphics section.
8) Export figures or data from the Export section.

-------------------------------------------------------

4. Peak Detection and Editing

SpecLab supports both automatic and manual peak workflows.

Automatic detection:
- Uses current peak settings and can run for the active spectrum or all spectra.

Manual peak picking:
- Click on the plot to add a manual peak label at the clicked X position.
- Peak Y is derived from the displayed curve.

Deleting peaks:
- Shift + Left Click on a peak label
  or
- Click a peak label to select it, then press Backspace/Delete

Peak sources:
- AUTO detection
- MANUAL labels

-------------------------------------------------------

5. Exporting Data and Figures

Image export formats:
- PNG
- SVG

Data export formats:
- CSV
- TSV
- ZIP (for multi-spectrum batch exports)

Peak table exports include these columns:
- spectrum
- x
- y
- source (A = automatic, M = manual)

Image export size follows the current settings in the Graphics panel.

-------------------------------------------------------

6. Axis Labels and Formatting

Axis labels support superscript and subscript syntax directly in label text.

Examples:
- Raman shift (cm^-1)
- cm^{−1}
- E_corr
- CO_2

Supported syntax:
- ^x
- _x
- ^{...}
- _{...}

You can use these patterns anywhere in the label text.

-------------------------------------------------------

7. Tips

- Use overlay mode to compare spectral shifts and intensity changes across samples.
- For noisy data, tune peak detection parameters before final peak labeling.
- If labels overlap, reset label positions and re-adjust manually.
- Use presets to quickly reapply preferred styling and analysis settings.

-------------------------------------------------------

8. Troubleshooting

Problem: Program does not start
Solution: Reinstall SpecLab and/or restart Windows, then launch again.

Problem: Export cannot be saved
Solution: Check write permissions for the destination folder and verify the path is accessible.

Problem: Peak labels cannot be deleted
Solution: Click directly on the label text first, then press Delete/Backspace, or use Shift + click.

-------------------------------------------------------

9. Version

SpecLab version: 0.1.0

-------------------------------------------------------

10. Author / Support

Created by:
Jakub Havránek

Contact:
Personal email:
jakubhavranek120@gmail.com

Academic / institutional email:
havranek@vscht.cz

If you encounter bugs or issues, please report them through the project repository or contact the author.
