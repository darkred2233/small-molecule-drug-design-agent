import { useEffect, useRef } from 'react';
import SmilesDrawer from 'smiles-drawer';

function drawFallback(canvas: HTMLCanvasElement) {
  const context = canvas.getContext('2d');
  if (!context) return;
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.fillStyle = '#66756f';
  context.font = '24px sans-serif';
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText('?', canvas.width / 2, canvas.height / 2);
}

export function MoleculeThumbnail({ smiles, className = '' }: { smiles: string; className?: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !smiles) return;

    let cancelled = false;
    const fallback = () => {
      if (!cancelled) drawFallback(canvas);
    };
    const drawer = new SmilesDrawer.Drawer({ width: 156, height: 108, padding: 6, compactDrawing: true, explicitHydrogens: false, terminalCarbons: false });

    SmilesDrawer.parse(
      smiles,
      (tree) => {
        if (cancelled) return;
        try {
          drawer.draw(tree, canvas, 'light', false);
        } catch {
          fallback();
        }
      },
      fallback,
    );

    return () => {
      cancelled = true;
    };
  }, [smiles]);

  return <canvas ref={canvasRef} className={`structure-box ${className}`} width={156} height={108} aria-label="分子二维结构" />;
}
