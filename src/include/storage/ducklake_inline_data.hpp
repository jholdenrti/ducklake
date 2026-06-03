//===----------------------------------------------------------------------===//
//                         DuckDB
//
// storage/ducklake_inline_data.hpp
//
//
//===----------------------------------------------------------------------===//

#pragma once

#include "duckdb/execution/physical_operator.hpp"
#include "duckdb/common/index_vector.hpp"
#include "storage/ducklake_stats.hpp"
#include "common/ducklake_data_file.hpp"

namespace duckdb {
class DuckLakeInsert;

class DuckLakeInlineData : public PhysicalOperator {
public:
	static constexpr const PhysicalOperatorType TYPE = PhysicalOperatorType::EXTENSION;

public:
	DuckLakeInlineData(PhysicalPlan &physical_plan, PhysicalOperator &child, idx_t inline_row_limit);
	//! Variant that sets the operator types explicitly instead of inheriting them from `child`. Used by
	//! MERGE INTO ... WHEN NOT MATCHED, where the rows fed to the operator come from the merge action
	//! expressions (physical columns) rather than from `child.types` (the insert op's BIGINT row-count).
	DuckLakeInlineData(PhysicalPlan &physical_plan, PhysicalOperator &child, vector<LogicalType> types,
	                   idx_t inline_row_limit);

	idx_t inline_row_limit;
	optional_ptr<DuckLakeInsert> insert;

public:
	unique_ptr<OperatorState> GetOperatorState(ExecutionContext &context) const override;
	unique_ptr<GlobalOperatorState> GetGlobalOperatorState(ClientContext &context) const override;
	OperatorResultType Execute(ExecutionContext &context, DataChunk &input, DataChunk &chunk,
	                           GlobalOperatorState &gstate, OperatorState &state) const override;
	OperatorFinalizeResultType FinalExecute(ExecutionContext &context, DataChunk &chunk, GlobalOperatorState &gstate,
	                                        OperatorState &state) const override;
	OperatorFinalResultType OperatorFinalize(Pipeline &pipeline, Event &event, ClientContext &context,
	                                         OperatorFinalizeInput &input) const override;

	bool RequiresFinalExecute() const override {
		return true;
	}
	bool RequiresOperatorFinalize() const override {
		return true;
	}
	bool ParallelOperator() const override {
		return true;
	}
	string GetName() const override;
};

} // namespace duckdb
