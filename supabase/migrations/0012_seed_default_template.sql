-- 0012 — Seed the default Gate 0-7 stage-gate template.
--
-- READ THIS BEFORE USING IT.
--
-- This content is STRUCTURAL SCAFFOLDING, not regulatory advice. It gives an
-- organisation a complete, coherent starting point so nobody faces an empty
-- screen — but which requirements are genuinely mandatory for a given product,
-- in a given market, under a given regulatory pathway, is domain knowledge that
-- must come from the organisation's own scientific, quality and regulatory
-- people.
--
-- The template is therefore seeded with status = 'draft' and no approver. The
-- template_active_requires_approval constraint means it CANNOT be activated,
-- and therefore cannot be instantiated onto a project, until a human with
-- authority has reviewed and approved it. That is deliberate friction.
--
-- Note what is absent by design: there is no requirement anywhere asking for a
-- freedom-to-operate conclusion. G2-IP-002 requests an *instruction to patent
-- counsel*, because an FTO opinion is a legal act this system must never
-- produce or imply.

do $$
declare
  t_id uuid;
  s0 uuid; s1 uuid; s2 uuid; s3 uuid; s4 uuid; s5 uuid; s6 uuid; s7 uuid;
begin

insert into public.pdp_templates (
  template_key, version, name, description, product_type, status, is_default
) values (
  'default_pdp', 1,
  'Default Product Development Programme (Gate 0-7)',
  'Structural starting template covering concept through launch. Provided as '
  'scaffolding only: requirements, mandatory flags, weights and acceptance '
  'criteria must be reviewed and approved by the organisation''s scientific, '
  'quality and regulatory functions before use. Not regulatory advice.',
  'general', 'draft', false
) returning id into t_id;

-- ---------------------------------------------------------------- the stages ---

insert into public.template_stages (template_id, position, key, name, gate_question, exit_criteria) values
 (t_id, 0, 'gate_0', 'Gate 0: Product concept and opportunity assessment',
  'Is this opportunity worth spending development resource to explore?',
  'A defined product concept with a credible commercial and scientific rationale.'),
 (t_id, 1, 'gate_1', 'Gate 1: Feasibility and preformulation',
  'Is the concept scientifically feasible with this molecule and technology?',
  'Preformulation data supporting feasibility, with risks identified.'),
 (t_id, 2, 'gate_2', 'Gate 2: Formulation candidate selection',
  'Which formulation do we take forward, and why that one?',
  'A selected candidate with documented rationale and supporting data.'),
 (t_id, 3, 'gate_3', 'Gate 3: Process and analytical readiness',
  'Can we make it reproducibly and measure it reliably?',
  'Defined process, developed analytical methods, identified CPPs and CQAs.'),
 (t_id, 4, 'gate_4', 'Gate 4: Pilot or clinical batch readiness',
  'Are we ready to manufacture material for clinical or pilot use?',
  'Approved batch documentation, stability protocol and nonclinical package.'),
 (t_id, 5, 'gate_5', 'Gate 5: Registration readiness',
  'Do we have the package needed to submit?',
  'Complete CMC package with validated methods and sufficient stability data.'),
 (t_id, 6, 'gate_6', 'Gate 6: Technology transfer and commercial readiness',
  'Can the receiving site make this at commercial scale?',
  'Successful transfer, validated process, qualified supply chain.'),
 (t_id, 7, 'gate_7', 'Gate 7: Launch and lifecycle management',
  'Are we ready to launch and to sustain the product?',
  'Launch readiness confirmed with lifecycle commitments in place.');

select id into s0 from public.template_stages where template_id = t_id and key = 'gate_0';
select id into s1 from public.template_stages where template_id = t_id and key = 'gate_1';
select id into s2 from public.template_stages where template_id = t_id and key = 'gate_2';
select id into s3 from public.template_stages where template_id = t_id and key = 'gate_3';
select id into s4 from public.template_stages where template_id = t_id and key = 'gate_4';
select id into s5 from public.template_stages where template_id = t_id and key = 'gate_5';
select id into s6 from public.template_stages where template_id = t_id and key = 'gate_6';
select id into s7 from public.template_stages where template_id = t_id and key = 'gate_7';

-- ------------------------------------------------------------------- Gate 0 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s0, 1, 'G0-PM-001', 'Draft target product profile',
  'Intended indication, route, dosage form, dose, and the clinical need being addressed.',
  'project_management', true, 3, 'document', 'Target Product Profile',
  'States indication, route, dosage form and the differentiation being sought.', 14, 'project_manager'),
 (s0, 2, 'G0-CO-001', 'Commercial opportunity assessment',
  'Market size, competitive landscape, and the commercial case for development.',
  'commercial', true, 2, 'document', 'Commercial Assessment',
  'Quantifies opportunity with stated assumptions and their sources.', 21, 'department_head'),
 (s0, 3, 'G0-IP-001', 'Preliminary patent landscape review',
  'Initial view of the patent landscape around the molecule and delivery technology.',
  'intellectual_property', true, 2, 'research_run', null,
  'Identifies relevant patent families and their assignees. Research support only, not a legal opinion.', 21, 'project_manager'),
 (s0, 4, 'G0-RA-001', 'Preliminary regulatory pathway assessment',
  'Likely regulatory route, precedents, and the principal regulatory unknowns.',
  'regulatory', true, 2, 'document', 'Regulatory Assessment',
  'Names the intended pathway and lists the questions requiring agency input.', 21, 'regulatory_reviewer'),
 (s0, 5, 'G0-FD-001', 'Scientific feasibility rationale',
  'Why this technology is plausible for this molecule, with the evidence supporting it.',
  'formulation', true, 3, 'research_run', null,
  'Cites retrieved evidence. Distinguishes demonstrated results from assumptions.', 21, 'senior_scientist'),
 (s0, 6, 'G0-PM-002', 'Resource and budget estimate',
  'Indicative resource, cost and timeline to the next gate.',
  'project_management', false, 1, 'document', 'Project Plan',
  'Covers headcount, external spend and elapsed time to Gate 1.', 28, 'project_manager');

-- ------------------------------------------------------------------- Gate 1 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s1, 1, 'G1-FD-001', 'API characterisation report',
  'Physicochemical characterisation of the drug substance.',
  'formulation', true, 3, 'document', 'Characterisation Report',
  'Covers solubility, stability, solid form and impurity profile as applicable.', 30, 'senior_scientist'),
 (s1, 2, 'G1-FD-002', 'Preformulation study report',
  'Preformulation work establishing the behaviour of the molecule in the intended system.',
  'formulation', true, 3, 'document', 'Preformulation Report',
  'Reports methods, results and limitations. Negative findings included.', 45, 'formulation_lead'),
 (s1, 3, 'G1-FD-003', 'Literature review of the delivery technology',
  'Structured review of published evidence for the proposed delivery approach.',
  'formulation', true, 2, 'research_run', null,
  'Every claim traceable to a retrieved source. Evidence gaps stated explicitly.', 30, 'senior_scientist'),
 (s1, 4, 'G1-FD-004', 'Excipient and material compatibility screening',
  'Compatibility of the drug substance with candidate excipients and materials.',
  'formulation', true, 2, 'data', null,
  'Covers the materials proposed for the candidate formulation.', 60, 'formulation_lead'),
 (s1, 5, 'G1-AN-001', 'Analytical method feasibility',
  'Whether methods exist or can be developed to measure the required attributes.',
  'analytical', true, 2, 'document', 'Analytical Development Report',
  'Confirms a measurement approach for each provisional CQA.', 45, 'analytical_lead'),
 (s1, 6, 'G1-QA-001', 'Preliminary critical quality attribute identification',
  'First identification of attributes likely to be critical to safety and efficacy.',
  'quality', true, 3, 'document', 'CQA Assessment',
  'Each proposed CQA carries a stated rationale.', 45, 'quality_reviewer'),
 (s1, 7, 'G1-PM-001', 'Preliminary risk assessment',
  'Development risks with likelihood, impact and proposed mitigation.',
  'project_management', true, 2, 'document', 'Risk Assessment',
  'Covers technical, analytical, regulatory and supply risk.', 45, 'project_manager'),
 (s1, 8, 'G1-NC-001', 'Nonclinical strategy outline',
  'Outline of the nonclinical work the programme will require.',
  'nonclinical', false, 1, 'document', 'Nonclinical Plan',
  'Identifies studies needed and the questions each answers.', 60, 'senior_scientist');

-- ------------------------------------------------------------------- Gate 2 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s2, 1, 'G2-FD-001', 'Prototype formulation report',
  'Prototypes prepared, how they were made, and how they performed.',
  'formulation', true, 3, 'document', 'Formulation Development Report',
  'Reports composition, process and results for each prototype.', 60, 'formulation_lead'),
 (s2, 2, 'G2-FD-002', 'Design of experiments study',
  'Structured study of the factors affecting the critical attributes.',
  'formulation', true, 3, 'data', null,
  'States the design, factors, responses and conclusions.', 90, 'formulation_lead'),
 (s2, 3, 'G2-FD-003', 'Screening stability data',
  'Short-term stability of the candidate formulations.',
  'formulation', true, 2, 'data', null,
  'Sufficient duration and conditions to discriminate between candidates.', 90, 'formulation_lead'),
 (s2, 4, 'G2-FD-004', 'Candidate selection rationale',
  'Which formulation is taken forward and the evidence supporting that choice.',
  'formulation', true, 3, 'document', 'Selection Rationale',
  'Compares candidates against defined criteria. Rejected options and reasons recorded.', 95, 'department_head'),
 (s2, 5, 'G2-IP-002', 'Instruction to patent counsel',
  'Brief prepared for qualified patent counsel covering the selected candidate. '
  'This system does not produce freedom-to-operate opinions; this requirement '
  'captures the instruction and counsel''s returned advice.',
  'intellectual_property', true, 2, 'document', 'Legal Instruction',
  'Counsel instructed and their written response recorded.', 95, 'project_manager'),
 (s2, 6, 'G2-PM-001', 'Updated target product profile',
  'TPP revised to reflect what has been learned.',
  'project_management', true, 2, 'document', 'Target Product Profile',
  'Changes from the previous version are visible and explained.', 95, 'project_manager'),
 (s2, 7, 'G2-AN-001', 'Analytical method development report',
  'Methods developed to support the selected candidate.',
  'analytical', true, 2, 'document', 'Analytical Development Report',
  'A method exists for each attribute needed at this stage.', 90, 'analytical_lead');

-- ------------------------------------------------------------------- Gate 3 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s3, 1, 'G3-MF-001', 'Process development report',
  'The manufacturing process, how it was arrived at, and how it behaves.',
  'manufacturing', true, 3, 'document', 'Process Development Report',
  'Describes unit operations, parameters and the development rationale.', 60, 'department_head'),
 (s3, 2, 'G3-QA-001', 'Critical process parameter identification',
  'Parameters that must be controlled, and the evidence they matter.',
  'quality', true, 3, 'document', 'CPP Assessment',
  'Each CPP linked to the CQA it affects, with supporting data.', 60, 'quality_reviewer'),
 (s3, 3, 'G3-QA-002', 'Critical material attribute identification',
  'Input material attributes affecting product quality.',
  'quality', true, 2, 'document', 'CMA Assessment',
  'Covers drug substance and each critical excipient.', 60, 'quality_reviewer'),
 (s3, 4, 'G3-AN-002', 'Analytical method validation protocol',
  'Protocol for validating the methods that will support release and stability.',
  'analytical', true, 3, 'document', 'Validation Protocol',
  'Defines parameters, acceptance criteria and rationale.', 75, 'analytical_lead'),
 (s3, 5, 'G3-MF-002', 'In-process controls defined',
  'Controls applied during manufacture, with their limits.',
  'manufacturing', true, 2, 'document', 'Process Control Strategy',
  'Each control linked to the parameter or attribute it governs.', 75, 'quality_reviewer'),
 (s3, 6, 'G3-MF-003', 'Scale-up risk assessment',
  'Risks arising from moving to a larger scale.',
  'manufacturing', true, 2, 'document', 'Risk Assessment',
  'Identifies scale-dependent parameters and proposed mitigation.', 90, 'department_head'),
 (s3, 7, 'G3-FD-001', 'Container-closure selection rationale',
  'Selected container-closure system and the evidence for it.',
  'formulation', true, 2, 'document', 'Selection Rationale',
  'Addresses compatibility, protection and, where relevant, delivery performance.', 90, 'formulation_lead'),
 (s3, 8, 'G3-AN-003', 'In vitro release testing strategy',
  'Approach to release testing, including its discriminatory ability.',
  'analytical', false, 2, 'document', 'Analytical Development Report',
  'States the method and the basis for believing it is discriminatory.', 90, 'analytical_lead');

-- ------------------------------------------------------------------- Gate 4 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s4, 1, 'G4-MF-001', 'Batch manufacturing record approved',
  'Approved record for the pilot or clinical batch.',
  'manufacturing', true, 3, 'document', 'Batch Record',
  'Reviewed and approved before manufacture begins.', 30, 'quality_reviewer'),
 (s4, 2, 'G4-MF-002', 'Pilot batch manufacturing report',
  'What was made, how it performed, and any deviations.',
  'manufacturing', true, 3, 'document', 'Batch Report',
  'Includes yield, in-process results and deviations with their disposition.', 60, 'quality_reviewer'),
 (s4, 3, 'G4-AN-001', 'Stability protocol approved',
  'Protocol defining the stability programme.',
  'analytical', true, 3, 'document', 'Stability Protocol',
  'Defines conditions, timepoints, tests and acceptance criteria.', 45, 'analytical_lead'),
 (s4, 4, 'G4-NC-001', 'Nonclinical package summary',
  'Nonclinical data supporting the intended use.',
  'nonclinical', true, 3, 'document', 'Nonclinical Summary',
  'Addresses the safety questions raised by the route and delivery system.', 60, 'senior_scientist'),
 (s4, 5, 'G4-QA-001', 'GMP readiness assessment',
  'Whether the manufacturing site is ready for this material.',
  'quality', true, 2, 'document', 'Readiness Assessment',
  'Covers facility, equipment, personnel and documentation.', 45, 'quality_reviewer'),
 (s4, 6, 'G4-CL-001', 'Clinical supply plan',
  'How clinical material will be supplied, labelled and distributed.',
  'clinical', false, 1, 'document', 'Supply Plan',
  'Covers quantities, timing and labelling requirements.', 60, 'project_manager');

-- ------------------------------------------------------------------- Gate 5 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s5, 1, 'G5-RA-001', 'CMC dossier sections drafted',
  'Chemistry, manufacturing and controls sections for the submission.',
  'regulatory', true, 3, 'document', 'Dossier Section',
  'Complete and internally consistent with the supporting data.', 90, 'regulatory_reviewer'),
 (s5, 2, 'G5-AN-001', 'Analytical method validation report',
  'Results of validating the methods used for release and stability.',
  'analytical', true, 3, 'document', 'Validation Report',
  'All protocol acceptance criteria met, or deviations justified.', 60, 'analytical_lead'),
 (s5, 3, 'G5-AN-002', 'Stability data package',
  'Stability data supporting the proposed shelf life and storage.',
  'analytical', true, 3, 'data', null,
  'Sufficient duration and conditions for the claim being made.', 90, 'analytical_lead'),
 (s5, 4, 'G5-MF-001', 'Process validation strategy',
  'Approach to demonstrating the process performs consistently.',
  'manufacturing', true, 2, 'document', 'Validation Strategy',
  'Defines the lifecycle approach and acceptance criteria.', 75, 'department_head'),
 (s5, 5, 'G5-RA-002', 'Regulatory submission plan',
  'Markets, sequence, timing and requirements for submission.',
  'regulatory', true, 2, 'document', 'Submission Plan',
  'Names target markets with their specific requirements.', 75, 'regulatory_reviewer'),
 (s5, 6, 'G5-RA-003', 'Labelling and artwork assessment',
  'Proposed labelling and its regulatory basis.',
  'regulatory', false, 1, 'document', 'Labelling Assessment',
  'Aligns with the submitted data and market requirements.', 90, 'regulatory_reviewer');

-- ------------------------------------------------------------------- Gate 6 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s6, 1, 'G6-MF-001', 'Technology transfer protocol',
  'Protocol governing transfer to the receiving site.',
  'manufacturing', true, 3, 'document', 'Transfer Protocol',
  'Defines scope, responsibilities and acceptance criteria.', 45, 'department_head'),
 (s6, 2, 'G6-MF-002', 'Receiving site readiness assessment',
  'Whether the receiving site can execute the process.',
  'manufacturing', true, 2, 'document', 'Readiness Assessment',
  'Covers equipment, utilities, personnel and analytical capability.', 60, 'quality_reviewer'),
 (s6, 3, 'G6-MF-003', 'Process validation report',
  'Evidence the process performs consistently at commercial scale.',
  'manufacturing', true, 3, 'document', 'Validation Report',
  'All acceptance criteria met across the validation batches.', 120, 'quality_reviewer'),
 (s6, 4, 'G6-QA-001', 'Supply chain qualification',
  'Qualification of material suppliers and contract manufacturers.',
  'quality', true, 2, 'document', 'Qualification Report',
  'Each critical supplier qualified with the evidence recorded.', 90, 'quality_reviewer'),
 (s6, 5, 'G6-PM-001', 'Training completion for the receiving site',
  'Personnel trained on the transferred process and methods.',
  'project_management', true, 2, 'document', 'Training Record',
  'Completion recorded for every role required to execute.', 90, 'training_administrator');

-- ------------------------------------------------------------------- Gate 7 ---

insert into public.template_requirements
 (template_stage_id, position, ref_code, title, description, discipline,
  is_mandatory, weight, required_evidence_type, required_document_type,
  acceptance_criteria, default_lead_days, approver_role_key) values
 (s7, 1, 'G7-PM-001', 'Launch readiness review',
  'Cross-functional confirmation that launch can proceed.',
  'project_management', true, 3, 'document', 'Readiness Review',
  'Every function has confirmed readiness, with open items listed.', 30, 'executive'),
 (s7, 2, 'G7-AN-001', 'Post-approval stability commitment',
  'Ongoing stability programme for commercial batches.',
  'analytical', true, 2, 'document', 'Stability Protocol',
  'Defines the commitment made in the submission.', 30, 'analytical_lead'),
 (s7, 3, 'G7-QA-001', 'Change control plan',
  'How post-approval changes will be assessed and managed.',
  'quality', true, 2, 'document', 'Change Control Plan',
  'Defines categories, assessment route and regulatory reporting.', 45, 'quality_reviewer'),
 (s7, 4, 'G7-PM-002', 'Lifecycle management plan',
  'Planned lifecycle activities and continued improvement.',
  'project_management', false, 1, 'document', 'Lifecycle Plan',
  'Identifies planned changes and their approximate timing.', 60, 'project_manager');

-- ------------------------------------------------------------- dependencies ---
-- Only genuine ordering constraints. Over-specifying dependencies makes a plan
-- brittle and produces cascades of false blockers, so this is deliberately
-- sparse: a candidate cannot be selected before prototypes exist and have been
-- studied; CPPs cannot be identified before the process is developed; a batch
-- cannot be made before its record is approved; a validation report cannot
-- precede its protocol.

insert into public.template_requirement_dependencies (requirement_id, depends_on_id)
select r.id, d.id
  from public.template_requirements r
  join public.template_stages rs on rs.id = r.template_stage_id
  join public.template_requirements d on true
  join public.template_stages ds on ds.id = d.template_stage_id
 where rs.template_id = t_id and ds.template_id = t_id
   and (r.ref_code, d.ref_code) in (
     ('G2-FD-004', 'G2-FD-001'),   -- selection needs prototypes
     ('G2-FD-004', 'G2-FD-002'),   -- selection needs the DoE
     ('G2-FD-004', 'G2-FD-003'),   -- selection needs screening stability
     ('G3-QA-001', 'G3-MF-001'),   -- CPPs need a developed process
     ('G3-QA-002', 'G3-MF-001'),   -- CMAs need a developed process
     ('G4-MF-002', 'G4-MF-001'),   -- batch report needs an approved record
     ('G5-AN-001', 'G3-AN-002'),   -- validation report needs its protocol
     ('G6-MF-003', 'G6-MF-001'),   -- validation needs the transfer protocol
     ('G7-PM-001', 'G6-MF-003')    -- launch needs process validation
   );

end $$;
