import { useState } from "react";
import { Modal } from "../ui";
import { ChevronDown, ChevronUp } from "lucide-react";

export function ProcessConfigModal({ open, onClose, onStart }) {
  const [config, setConfig] = useState({
    projectName: "",
    projectDescription: "",
    maxIterations: 150,
  });

  const [expandedSections, setExpandedSections] = useState({
    basic: true,
    stakeholders: true,
    advanced: false,
  });

  const toggleSection = (section) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onStart(config);
    onClose();
    setConfig({
      projectName: "",
      projectDescription: "",
      maxIterations: 150,
    });
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Requirements Process Configuration"
      width="max-w-[520px]"
    >
      <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-4">
        {/* Basic Section */}
        <div className="mb-4 border border-[#E5E5E5] rounded-lg bg-[#FFFFFF] overflow-hidden">
          <button
            type="button"
            onClick={() => toggleSection("basic")}
            className="w-full flex items-center justify-between p-3 text-[#1A1A1A] hover:bg-[#F8F8F8] transition-colors"
          >
            <span className="font-medium">Basic Configuration</span>
            {expandedSections.basic ? (
              <ChevronUp className="w-4 h-4 text-[#6B6B6B]" />
            ) : (
              <ChevronDown className="w-4 h-4 text-[#6B6B6B]" />
            )}
          </button>

          {expandedSections.basic && (
            <div className="p-3 pt-0 space-y-3">
              <div>
                <label className="block text-sm font-medium mb-1 text-[#3A3A3A]">
                  Project Name *
                </label>
                <input
                  type="text"
                  value={config.projectName}
                  onChange={(e) =>
                    setConfig({ ...config, projectName: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-[#F8F8F8] border border-[#E5E5E5] rounded-lg text-[#1A1A1A] placeholder:text-[#A0A0A0] focus:ring-2 focus:ring-[#B86F50]/20 focus:border-[#B86F50]/60 focus:outline-none transition-all"
                  placeholder="Enter project name"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1 text-[#3A3A3A]">
                  Project Description *
                </label>
                <textarea
                  value={config.projectDescription}
                  onChange={(e) =>
                    setConfig({ ...config, projectDescription: e.target.value })
                  }
                  className="w-full px-3 py-2 bg-[#F8F8F8] border border-[#E5E5E5] rounded-lg text-[#1A1A1A] placeholder:text-[#A0A0A0] focus:ring-2 focus:ring-[#B86F50]/20 focus:border-[#B86F50]/60 focus:outline-none transition-all"
                  placeholder="Enter project description"
                  required
                  style={{
                    fieldSizing: "content",
                  }}
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1 text-[#3A3A3A]">
                  Max Iterations
                </label>
                <input
                  type="number"
                  min="5"
                  max="200"
                  value={config.maxIterations}
                  onChange={(e) =>
                    setConfig({
                      ...config,
                      maxIterations: parseInt(e.target.value),
                    })
                  }
                  className="w-full px-3 py-2 bg-[#F8F8F8] border border-[#E5E5E5] rounded-lg text-[#1A1A1A] focus:ring-2 focus:ring-[#B86F50]/20 focus:border-[#B86F50]/60 focus:outline-none transition-all"
                />
              </div>
            </div>
          )}
        </div>
      </form>

      <div className="flex justify-end gap-3 p-4 border-t border-[#E5E5E5]">
        <button
          onClick={onClose}
          className="px-4 py-2 border border-[#E5E5E5] rounded-lg text-[#3A3A3A] hover:bg-[#EFEFEF] hover:border-[#C5C5C5] transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSubmit}
          className="px-4 py-2 bg-[#B86F50] text-white rounded-lg hover:bg-[#A76145]"
        >
          Start Process
        </button>
      </div>
    </Modal>
  );
}
