/**
 * Molecule Structure Component
 *
 * Renders 2D molecule structure using SmilesDrawer
 */

import { useEffect, useRef } from 'react';

interface MoleculeStructureProps {
  smiles: string;
  width?: number;
  height?: number;
  className?: string;
}

export default function MoleculeStructure({
  smiles,
  width = 300,
  height = 300,
  className = '',
}: MoleculeStructureProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const drawMolecule = async () => {
      if (!canvasRef.current) return;

      try {
        // Dynamically import SmilesDrawer
        const SmilesDrawer = (await import('smiles-drawer')).default;

        const options = {
          width,
          height,
          bondThickness: 0.6,
          bondLength: 15,
          shortBondLength: 0.85,
          bondSpacing: 0.18 * 15,
          atomVisualization: 'default',
          isomeric: true,
          debug: false,
          terminalCarbons: false,
          explicitHydrogens: false,
          overlapSensitivity: 0.42,
          overlapResolutionIterations: 1,
          compactDrawing: true,
          fontFamily: 'Arial, Helvetica, sans-serif',
          fontSizeLarge: 6,
          fontSizeSmall: 4,
          padding: 20,
        };

        const drawer = new SmilesDrawer.Drawer(options);

        SmilesDrawer.parse(smiles, (tree: any) => {
          const canvas = canvasRef.current;
          if (!canvas) return;
          drawer.draw(tree, canvas, 'light', false);
        });
      } catch (error) {
        console.error('Failed to draw molecule:', error);
        // Draw error message on canvas
        const ctx = canvasRef.current?.getContext('2d');
        if (ctx) {
          ctx.fillStyle = '#ef4444';
          ctx.font = '14px Arial';
          ctx.textAlign = 'center';
          ctx.fillText('无法渲染分子结构', width / 2, height / 2);
        }
      }
    };

    drawMolecule();
  }, [smiles, width, height]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className={`molecule-canvas ${className}`}
    />
  );
}
