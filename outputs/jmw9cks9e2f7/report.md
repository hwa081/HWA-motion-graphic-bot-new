# Study report

Source: https://pin.it/3Pzsf94M0 (1529 characters)
New techniques: 5

- **Grid_Flood**: 1. Set background to a subtle color (background_style: solid). 2. Add a grid layer (grid) covering the screen at z-index 0. 3. Start with opacity 0. 4. Trigger entrance animation 'wipe_right' on the grid layer over 0.5s. 5. Simultaneously fade in a card (card) layer containing the main data point.
- **Card_Pop_Spin**: 1. Place a card (card) layer in the center at z-index 5, opacity 0. 2. Add a circle (circle) layer behind it at z-index 4, radius large, color accent. 3. Trigger entrance animation 'pop' on the circle over 0.3s. 4. Immediately trigger 'spin' on the card over 0.6s.
- **Chart_Rise_Glow**: 1. Create a chart (chart) layer at z-index 3, opacity 0. 2. Add a line (line) layer on top of the chart at z-index 4. 3. Use entrance animation 'rise' for the chart over 0.8s. 4. Apply entrance animation 'zoom' with scale 1.2 to the specific line segment representing the peak.
- **Iris_Divider**: 1. Set background to a neutral style (background_style: solid). 2. Create a card (card) layer covering the full screen at z-index -1, opacity 0. 3. Use transition 'iris' for the card over 0.5s to create the reveal effect.
- **Blob_Scale_Entrance**: 1. Place a blob (blob) layer at z-index 2, opacity 0. 2. Set color to match brand accent. 3. Trigger entrance animation 'zoom' over 0.4s from scale 0 to 1.

Total techniques in the notebook: 35