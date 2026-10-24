"use client";

import { useRef } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Html } from "@react-three/drei";
import type { Group } from "three";

const stages = [
  { label: "Company grievance", color: "#d7c39a" },
  { label: "RBI Ombudsman", color: "#e1d4b4" },
  { label: "Consumer Helpline", color: "#e7ddc8" },
  { label: "Consumer Commission", color: "#eee7d9" },
];

function Staircase({ animate }: { animate: boolean }) {
  const world = useRef<Group>(null);
  useFrame(({ clock }) => {
    if (!world.current || !animate) return;
    world.current.rotation.y = -0.26 + Math.sin(clock.elapsedTime * 0.22) * 0.025;
    world.current.position.y = Math.sin(clock.elapsedTime * 0.38) * 0.018;
  });

  return <group ref={world} rotation={[-0.08, -0.26, 0]} position={[0.18, -0.28, 0]}>
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -1.18, 0]} receiveShadow><planeGeometry args={[12, 8]}/><meshStandardMaterial color="#f3f5f8" roughness={1}/></mesh>
    {stages.map((stage, index) => {
      const x = -2.18 + index * 1.12;
      const y = -0.88 + index * 0.35;
      const current = index === 0;
      return <group key={stage.label} position={[x, y, 0]}>
        <mesh castShadow receiveShadow position={[0, 0, 0]}><boxGeometry args={[1.18, 0.36, 1.45]}/><meshStandardMaterial color={index === 0 ? "#d5c092" : "#dfe3e9"} roughness={0.82}/></mesh>
        <mesh position={[0, 0.188, 0]}><boxGeometry args={[1.2, 0.025, 1.47]}/><meshStandardMaterial color={index === 0 ? "#eadbb7" : "#f9f8f4"} roughness={0.95}/></mesh>
        <group position={[-0.05, 0.38, 0]} rotation={[0, 0, current ? -0.09 : 0.04]}>
          <mesh castShadow position={[0, 0, 0]}><boxGeometry args={[0.7, 0.11, 0.47]}/><meshStandardMaterial color={stage.color} roughness={0.9}/></mesh>
          <mesh position={[-0.13, 0.067, -0.03]}><boxGeometry args={[0.38, 0.025, 0.42]}/><meshStandardMaterial color={current ? "#e7d8b3" : "#f0ece2"} roughness={0.9}/></mesh>
          <mesh position={[0.16, 0.079, -0.09]}><boxGeometry args={[0.18, 0.012, 0.12]}/><meshStandardMaterial color="#b9a77b" roughness={0.85}/></mesh>
          {current && <mesh position={[0, 0.064, 0.235]}><boxGeometry args={[0.18, 0.07, 0.012]}/><meshStandardMaterial color="#b83e37" roughness={0.45}/></mesh>}
        </group>
        <Html position={[0, 0.63, 0.5]} center distanceFactor={8} transform={false} zIndexRange={[10, 0]}>
          <div className={`scene-label ${current ? "scene-label-current" : ""}`}><span>{String(index + 1).padStart(2, "0")}</span>{stage.label}</div>
        </Html>
      </group>;
    })}
    <mesh castShadow position={[0.35, -0.38, -0.52]} rotation={[0, 0.11, -0.12]}>
      <boxGeometry args={[0.62, 0.09, 0.42]}/><meshStandardMaterial color="#4a3aa8" roughness={0.68}/>
    </mesh>
    <Html position={[0.35, -0.16, -0.55]} center distanceFactor={8} transform={false} zIndexRange={[10, 0]}>
      <div className="scene-proof"> <span/>RULE SOURCE · STORED</div>
    </Html>
  </group>;
}

export function HeroScene({ reducedMotion = false, tier = "full" }: { reducedMotion?: boolean; tier?: "full" | "lite" }) {
  return <div className="hero-scene-layer" aria-hidden="true">
    <Canvas dpr={tier === "lite" ? 1 : [1, 1.5]} shadows={tier === "full"} camera={{ position: [0.2, 3.3, 8.8], fov: 35 }} gl={{ alpha: true, antialias: tier === "full", powerPreference: "low-power" }}>
      <ambientLight intensity={1.35}/>
      <directionalLight position={[-3, 7, 5]} intensity={2.6} castShadow shadow-mapSize-width={1024} shadow-mapSize-height={1024}/>
      <directionalLight position={[5, 2, -3]} intensity={0.65} color="#b6b5ff"/>
      <Staircase animate={!reducedMotion}/>
    </Canvas>
  </div>;
}
