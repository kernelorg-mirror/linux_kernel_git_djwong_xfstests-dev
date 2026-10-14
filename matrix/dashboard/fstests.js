/*
 * SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2018-2026 Oracle.
 */
var DEBUG = document.location.hash.indexOf('debug') >= 0;
var MAX_PER_PAGE = 120; /* lcm of 2, 3, 4, 5, 6 that's greater than 100 */

function log(msg) {
	if (!DEBUG)
		return;

	var dateopts = {
		hour12: false,
		weekday: 'short',
		year: 'numeric',
		month: 'short',
		day: 'numeric',
		hour: 'numeric',
		minute: 'numeric',
		timeZoneName: 'short',
	};

	var d = new Date();
	s = d.toLocaleString('en-US', dateopts) + ":";
	console.log(s, msg);
}

class TestRun {
	constructor()
	{
	}

	absorb(raw, dateopts)
	{
		this.data = raw;
		this.dateopts = dateopts;

		/*
		 * From the junit xml reports, we have some summary counters:
		 *  - failed/failures: # of real test failures;
		 *  - tried/tests: # of tests we chose for this test run;
		 *  - skipped: # of tests that declined to run;
		 *  - counted: # of tests in the fingerprint file.
		 *
		 * # of tests attempted so far is (tried - skipped).
		 * # of tests that passed so far is (attempted - failed).
		 */
		this.data.attempted = this.data.tried - this.data.skipped;
		this.data.passed = this.data.attempted - this.data.failed;
		this.data.notsel = this.data.counted - this.data.tried;
	}

	/* Render a fraction as a human-readable percentage. */
	_human_pct(n, d) {
		if (n <= 0)
			return '0%';
		if (d == 0)
			d += 1;
		var pct = 100.0 * n / d;
		if (pct >= 10)
			return pct.toFixed(0) + '%';
		if (pct >= 1)
			return pct.toFixed(1) + '%';
		if (pct >= 0.1)
			return pct.toFixed(2) + '%';
		return pct.toFixed(3) + '%';
	}

	_num(nr) {
		try {
			/* Not supported on Safari 9 */
			return Intl.NumberFormat().format(nr);
		} catch (err) {
			return nr;
		}
	}

	/* Render numerical status. */
	_summary(nr) {
		var raw = this.data;
		var status1 = this._num(nr) + ' of ' + this._num(raw.attempted);
		status1 += ' (' + this._human_pct(nr, raw.attempted) + ') tests';
		if (raw.run_time == null)
			status1 += ' so far';

		/*
		 * If we ran fewer than 100 tests then assume we weren't trying
		 * for a comprehensive QA run.  Coverage here is defined as
		 * tests that passed, failed, or weren't appropriate for the
		 * fs configuration (i.e. _notrun).
		 */
		if (raw.attempted >= 100) {
			status1 += ', covering ';
			status1 += this._human_pct(raw.tried, raw.counted);
			status1 += ' of ' + this._num(raw.counted);
		}

		/* Estimate the amount of time elapsed so far. */
		if (raw.run_time == null) {
			var elapsed = (Date.now() / 1000) - raw.start_time;
			status1 += ' after ';
		} else {
			var elapsed = raw.run_time;
			status1 += ' in ';
		}
		if (elapsed >= 86400) {
			status1 += (elapsed / 86400).toFixed(1) + ' days.';
		} else if (elapsed >= 3600) {
			status1 += (elapsed / 3600).toFixed(1) + ' hours.';
		} else if (elapsed >= 60) {
			status1 += (elapsed / 60).toFixed(0) + ' mins.';
		} else {
			status1 += elapsed.toFixed(0) + ' secs.';
		}
		return status1;
	}

	/* Render status message. */
	_status()
	{
		var raw = this.data;
		var p = $('<span>');

		/* Still running... */
		if (raw.run_time == null) {
			var ctx = this._summary(raw.passed);
			var stat = $('<span>');
			if (raw.late) {
				stat.attr('class', 'late');
				stat.text('Running Late');
			} else {
				stat.attr('class', 'running');
				stat.text('Running');
			}
			return p.append(stat).append(', passed ').append(ctx);
		}

		/* Finished without running anything. */
		if (raw.attempted < 1)
			return p.text('Did not run any tests.');

		/* Finished with failures. */
		if (raw.failed > 0) {
			var ctx = this._summary(raw.failed);
			var stat = $('<span>');
			stat.attr('class', 'failed');
			stat.text('Failed');
			return p.append(stat).append(' ').append(ctx);
		}

		/* Everything passed! */
		ctx = this._summary(raw.passed);
		var stat = $('<span>');
		stat.attr('class', 'passed');
		stat.text('Passed');
		return p.append(stat).append(' all ').append(ctx);
	}

	/* Render tooltip for progress bar. */
	_tooltip(n, tag) {
		var ret = this._num(n) + ' ' + tag + ' (';
		ret += this._human_pct(n, this.data.counted) + ')';
		return ret;
	}

	/* Create a HTML progressbar. */
	_progressbar() {
		function pct(n, d) {
			return (100.0 * n / d) + '%';
		}
		var pb = $('<div>');
		pb.attr('class', 'progress_bar');

		var raw = this.data;
		var ppass = $('<div>');
		ppass.attr('class', 'progress_rect progress_pass');
		var pstr = pct(raw.passed, raw.counted);
		ppass.css('width', pstr);
		var tstr = this._tooltip(raw.passed, 'Passed');
		ppass.attr('title', tstr);
		pb.append(ppass);

		var pfail = $('<div>');
		pfail.attr('class', 'progress_rect progress_fail');
		var pstr = pct(raw.failed, raw.counted);
		pfail.css('width', pstr);
		var tstr = this._tooltip(raw.failed, 'Failed');
		pfail.attr('title', tstr);
		pb.append(pfail);

		var pskip = $('<div>');
		pskip.attr('class', 'progress_rect progress_skip');
		var pstr = pct(raw.skipped, raw.counted);
		pskip.css('width', pstr);
		var tstr = this._tooltip(raw.skipped, 'Skipped');
		pskip.attr('title', tstr);
		pb.append(pskip);

		var pnosel = $('<div>');
		pnosel.attr('class', 'progress_rect progress_nosel');
		var pstr = pct(raw.notsel, raw.counted);
		pnosel.css('width', pstr);
		var tstr = this._tooltip(raw.notsel, 'Not Selected');
		pnosel.attr('title', tstr);
		pb.append(pnosel);

		return pb;
	}

	/* Generate a html status balloon. */
	render_html()
	{
		function mkfrob(str, tag) {
			if (tag === undefined || tag == null)
				tag = '<p>';
			var x = $(tag);
			x.html(str);
			return x;
		}
		function fixstring(str) {
			var s = str;
			s = s.replace(/-/g, '-<wbr/>');
			s = s.replace(/,/g, ',<wbr/>');
			s = s.replace(/=/g, '=<wbr/>');
			return s;
		}

		var raw = this.data;
		var cell = $('<div>');
		cell.attr('class', 'balloon');
		cell.append(mkfrob(raw.name, '<h2>'));
		cell.append(this._progressbar());

		var table = $('<div>');
		table.attr('class', 'propgrid');

		function longtablerow(table, key, value, longvalue) {
			var ltd = $('<div>');
			ltd.attr('class', 'propkey');
			ltd.text(key);
			var rtd = $('<div>');
			rtd.attr('class', 'propval');
			var details = $('<details>');
			details.attr('class', 'propval');
			var summary = $('<summary>');
			summary.html(value);
			var ellipse = $('<span>');
			ellipse.attr('class', 'ellipse');
			ellipse.html('…');
			summary.append(' ');
			summary.append(ellipse);
			details.append(summary);
			details.append(longvalue);
			rtd.append(details);
			table.append(ltd);
			table.append(rtd);
		}

		function tablerow(table, key, value, valueobj) {
			var ltd = $('<div>');
			ltd.attr('class', 'propkey');
			ltd.text(key);
			var rtd = $('<div>');
			rtd.attr('class', 'propval');
			rtd.html(value);
			if (valueobj != undefined) {
				rtd.append(' ');
				rtd.append(valueobj);
			}
			table.append(ltd);
			table.append(rtd);
		}

		var link = $('<a>');
		link.attr('class', 'resultslink');
		link.attr('target', '_blank');
		link.attr('rel', 'noopener');
		link.attr('href', 'output/.' + raw.machine_hash + '/.' + raw.test_run_hash + '/?C=M;O=A');
		link.html('🔗');

		var d = new Date(raw.time * 1000);
		tablerow(table, 'Updated:',
				d.toLocaleString('en-US', this.dateopts), link);

		/*
		 * Older versions of the reporter didn't consistently capture
		 * these datapoints, with the exception of FSTYP.
		 */
		if (raw.kernel != null)
			tablerow(table, 'Kernel:', fixstring(raw.kernel));
		if (raw.mkfs_opts != null)
			tablerow(table, 'Format:', 'mkfs.' + raw.fstyp + ' ' + fixstring(raw.mkfs_opts));
		if (raw.mount_opts != null)
			tablerow(table, 'Mount:', fixstring(raw.mount_opts));
		if (raw.testing != null)
			tablerow(table, 'Testing:', fixstring(raw.testing));
		if (raw.failed > 20) {
			var farray = raw.failures.split(" ");
			longtablerow(table, 'Failures:',
				fixstring(farray.slice(0, 20).join(" ")),
				fixstring(farray.slice(20).join(" ")));
		} else if (raw.failed > 0)
			tablerow(table, 'Failures:', fixstring(raw.failures));

		var ltd = $('<div>');
		ltd.attr('class', 'propkey');
		ltd.text('Status:');
		var rtd = $('<div>');
		rtd.attr('class', 'propval');
		rtd.append(this._status());
		table.append(ltd);
		table.append(rtd);

		cell.append(table);
		return cell;
	}
}

/* fstests status controller */
class FstestsCtl {
	constructor(url, other_url, other_link, refresh_s)
	{
		var that = this;
		this.div = $('#test_status');
		this.url = url;
		this.refreshTimer = null;
		this.dateopts = {
			hour12: false,
			weekday: 'short',
			year: 'numeric',
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: 'numeric',
			timeZoneName: 'short',
		};
		this.other_url = other_url;
		this.other_link = other_link;
		this.data = [];
		this.curr_page = 1;	/* 1 to nr_pages */
		this.nr_pages = 0;
		this.pager_div = null;
		this.refresh_s = refresh_s;
		this.mtime = null;

		/* fetch data now that we've finished building */
		this.fetch_data();
	}

	/* Set the automatic reload timeout. */
	_set_refresh_timer()
	{
		if (this.refreshTimer != null)
			window.clearTimeout(this.refreshTimer);

		if (this.refresh_s > 0) {
			var that = this;
			function timer_fn() {
				that.fetch_data(false);
			}
			this.refreshTimer = window.setTimeout(timer_fn,
					this.refresh_s * 1000);
		}
	}

	/* Load new test status data. */
	fetch_data()
	{
		log('load ' + this.url);
		var that = this;
		function kick(data, stat, xhr) {
			that.__load_data(data, stat, xhr);
			that._set_refresh_timer();
		}
		function fail() {
			that._set_refresh_timer();
		}
		$.getJSON(this.url, kick).fail(fail);
	}

	/* Install a new dataset into the control. */
	__set_data(data)
	{
		this.data = data;
		this.nr_pages = Math.ceil(data.length / MAX_PER_PAGE);

		/* Update the pager UI state. */
		this.pageinput.attr('max', this.nr_pages);
		this.pageinput.css('width', (1 + String(this.nr_pages).length) + 'em');
		this.pager_max.html(this.nr_pages);
		this.pager.show_if(this.nr_pages > 1);
	}

	/* Set the currently visible page. */
	__set_page(pagenr)
	{
		/* Negative pagenr is an offset from the end */
		if (pagenr < 0)
			pagenr = (pagenr + 1) + this.nr_pages;

		/* Clamp pagenr to 1..nr_pages */
		if (pagenr < 1)
			pagenr = 1;
		if (pagenr > this.nr_pages)
			pagenr = this.nr_pages;

		log('start_render ' + pagenr);

		/* Fill the page with html for just this part of the dataset */
		var page = $('<div>');
		page.attr('class', 'balloontab');

		/* Convert pagenr (1-based) to data[] (0-based) */
		var i = (pagenr - 1) * MAX_PER_PAGE;
		var max_i = Math.min(i + MAX_PER_PAGE, this.data.length);
		var tr = new TestRun();
		for (; i < max_i; i++) {
			tr.absorb(this.data[i], this.dateopts);
			page.append(tr.render_html());
		}

		this.pager_div.replaceWith(page);
		this.pager_div = page;
		this.curr_page = pagenr;

		log('finish_render ' + pagenr);

		/* Update the pager UI state. */
		this.rew.enable_if(this.curr_page > 1);
		this.prev.enable_if(this.curr_page > 1);
		this.next.enable_if(this.curr_page != this.nr_pages);
		this.ffwd.enable_if(this.curr_page != this.nr_pages);
		this.pageinput.val(this.curr_page);
	}

	/* Create the UI elements for where we display the test results */
	__render_balloons()
	{
		this.pager_div = $('<div>');
		this.div.empty();
		this.div.append(this.pager_div);
	}

	/* Render pager UI. */
	__render_pager()
	{
		var that = this;
		var enable_if = function(pred) {
			if (pred) {
				this.removeAttr('disabled');
			} else {
				this.attr('disabled', 'disabled');
			}
		};
		var show_if = function(pred) {
			if (pred) {
				this.show();
			} else {
				this.hide();
			}
		};

		var pager = $('<div>', {
			class: 'pager',
			disabled: true
		});
		pager.attr('class', 'pager');
		pager.show_if = show_if;
		pager.hide();

		/* Rewind to the start. */
		var rew = $('<button>', {
			class: 'pager_button',
			disabled: true
		});
		rew.html('&laquo;');
		rew.click(function() {
			that.__set_page(1);
			return false;
		});
		rew.enable_if = enable_if;
		pager.append(rew);
		this.rew = rew;

		/* Go back one page */
		var prev = $('<button>', {
			class: 'pager_button',
			disabled: true
		});
		prev.html('&lsaquo;');
		prev.click(function() {
			that.__set_page(that.curr_page - 1);
			return false;
		});
		prev.enable_if = enable_if;
		pager.append(prev);
		this.prev = prev;

		pager.append(' ');

		/* Where are we now? */
		var f = $('<form>', {
			id: 'pager_form',
			action: ''
		});
		f.submit(function() {
			var a = parseInt($('#pager_page').val());
			that.__set_page(a);
			return false;
		});
		var i = $('<input>', {
			type: 'number',
			value: this.curr_page,
			id: 'pager_page',
			min: 1,
			max: 1
		});
		i.css('width', '2em');
		this.pageinput = i;
		f.append(i);
		pager.append(f);
		pager.append(' of ');
		var np = $('<span>');
		this.pager_max = np;
		pager.append(np);
		pager.append(' ');

		/* Go forward one page. */
		var next = $('<button>', {
			class: 'pager_button',
			disabled: true
		});
		next.html('&rsaquo;');
		next.click(function() {
			that.__set_page(that.curr_page + 1);
			return false;
		});
		next.enable_if = enable_if;
		pager.append(next);
		this.next = next;

		/* Go to the end. */
		var ffwd = $('<button>', {
			class: 'pager_button',
			disabled: true
		});
		ffwd.html('&raquo;');
		ffwd.click(function() {
			that.__set_page(-1);
			return false;
		});
		ffwd.enable_if = enable_if;
		pager.append(ffwd);
		this.ffwd = ffwd;

		this.pager = pager;
		this.div.append(pager);
	}

	/* Create the last modified UI area. */
	__render_statusbar()
	{
		var hr = $('<hr/>');
		this.div.append(hr);
		var lastupdate = $('<div>', {
			class: "lastmod"
		});

		lastupdate.append('Last modified on ');
		var timestamp = $('<span>');
		lastupdate.append(timestamp);
		this.timestamp = timestamp;
		lastupdate.append('; also see ');
		var olink = $('<a>');
		olink.attr('href', this.other_url);
		olink.html(this.other_link);
		lastupdate.append(olink);
		lastupdate.append('.');

		this.div.append(lastupdate);
	}

	/* Fill out last modified timestamp. */
	__update_statusbar(mtime)
	{
		if (mtime == null)
			mtime = new Date();
		var timestamp = mtime.toLocaleString('en-US', this.dateopts);
		this.timestamp.html(timestamp);
	}

	/* Update UI with new status data. */
	__load_data(data, stat, xhr)
	{
		var mtime = null;

		log('nr_items ' + data.length);

		/* Define lateness as being more than 35 minutes out of date. */
		var late = Math.floor(Date.now() / 1000) - (35 * 60);

		/* Do we really need to update anything? */
		var lmtime = xhr.getResponseHeader('last-modified');
		if (lmtime != null)
			mtime = new Date(lmtime);
		log('old_mtime ' + this.mtime + '; mtime ' + mtime + '; equal ' + (this.mtime - mtime == 0));

		/*
		 * Oddly, '==' returns false for two separate Date objects
		 * that represent the same timestamp.  Subtracting them seems
		 * to work?
		 */
		if (this.mtime != null && mtime != null && this.mtime - mtime == 0) {
			/* update lateness data and re-render */
			var need_render = false;
			for (var testrun of this.data) {
				/* finished runs cannot be late */
				if (testrun.run_time != null)
					continue;
				var late_now = testrun.time < late;
				if (testrun.late == late_now)
					continue;
				log('now late: ' + testrun.name);
				testrun.late = testrun.time < late;
				need_render = true;
			}
			if (need_render)
				this.__set_page(this.curr_page);
			return;
		}

		/* Sort test results newest to oldest */
		data.sort(function c(a, b) {return b.time - a.time;});
		for (var testrun of data)
			testrun.late = testrun.time < late;

		log('processed_items ' + data.length);

		/* Create all UI elements */
		if (this.pager_div == null) {
			this.__render_balloons();
			this.__render_pager();
			this.__render_statusbar();
		}

		/* Replace any old dataset with the new dataset */
		this.mtime = mtime;
		this.__set_data(data);
		this.__set_page(this.curr_page);
		this.__update_statusbar(mtime);
	}
}

function loadFstestsAllCtl()
{
	/* no need to refresh this more than once per day */
	var timeout = 86400;
	if (DEBUG)
		timeout = 60;
	app = new FstestsCtl('fstestsall.js.br', './', 'most recent', timeout);
}

function loadFstestsBotCtl()
{
	/* refresh live results every few minutes */
	var timeout = 180;
	if (DEBUG)
		timeout = 60;
	app = new FstestsCtl('fstestsbot.js', 'all.html', 'full results', timeout);
}
