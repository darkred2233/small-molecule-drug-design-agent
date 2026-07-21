import { useEffect, useRef } from 'react';
import SmilesDrawer from 'smiles-drawer';

export function MoleculeThumbnail({ smiles, className = '' }: { smiles: string; className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !smiles) return;
    const drawer = new SmilesDrawer.Drawer({ width: 156, height: 108, padding: 6, compactDrawing: true, explicitHydrogens: false, terminalCarbons: false });
    drawer.draw(smiles, canvas, 'light', false);
  }, [smiles]);

  return <canvas ref={canvasRef} className={`structure-box ${className}`} width={156} height={108} aria-label="分子二维结构" />;
}
